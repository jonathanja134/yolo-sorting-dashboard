"""
yolo_detect_ncnn_headless.py ( YOLO inference +  buffer vote + serial protocol (Pi ↔ Arduino) + SocketIO → Flask + WebSocket Stream 

Category to Servo  mapping across all files:
  canister   → Servo 1 – pin 12
  chemical   → Servo 2 – pin 13
  applicator → Servo 3 – pin 14
  inhaler    → Servo 4 – pin 15

Serial protocol (Arduino → Pi):

  SENSOR:1:TRIGGERED / CLEAR
  SENSOR:2:TRIGGERED / CLEAR
  ACK:MOTOR:FORWARD / STOP
  ACK:LABEL:<category>
  SERVO:X:OPEN / CLOSED_OK / CLOSED_TIMEOUT / OBJECT_DETECTED / BLOCKED
  ERR:<detail>
  INFO:<detail>
"""
import serial, os, numpy as np, time, sys, termios, ncnn, cv2, threading, asyncio, websockets
from collections import Counter
from picamera2 import Picamera2
from ProgramManager.event_bus import configure_emit, _async_emit
from ProgramManager.serialManager import SerialManager, serial_reader, get_lamp_state
from ProgramManager.socketManager import SocketManager
from ProgramManager.Buffer import BufferManager,configure_buffer_manager
from ProgramManager.config import ( labels, num_classes, bbox_colors,input_size, conf_thresh, nms_thresh, min_frames, gap_limit,Yolo_model,
                                    LABEL_TO_CATEGORY, SERVO_INDEX_TO_CATEGORY, BAUD, PORT, DASHBOARD_URL)
from ProgramManager.ErrorManager import get_error_manager

# ── Model paths 
script_dir = os.path.dirname(os.path.abspath(__file__))
model_dir  = os.path.join(script_dir, "my_model_ncnn_model",Yolo_model)
param_file = os.path.join(model_dir, "model.ncnn.param")
bin_file   = os.path.join(model_dir, "model.ncnn.bin")

# ── Serial (Pi ↔ Arduino) 
serial = SerialManager(baud=BAUD)
print("~ 0 Serial Manager created")

# ── Conveyor motor state (conveyor_1 / pin 10) ──
motor_running = False
motor_lock    = threading.Lock()

def _get_conveyor_state():
    with motor_lock:
        return motor_running

def _set_conveyor_state(running):
    global motor_running
    with motor_lock:
        motor_running = running

# ── SocketIO → dashboard (before model load so startup errors are delivered) ───
socket_mgr = SocketManager(
    server_url=DASHBOARD_URL,
    get_conveyor_fn=_get_conveyor_state,
    set_conveyor_fn=_set_conveyor_state,
    serial_send_fn=serial.send,
    emit_fn=_async_emit,
    serial_ok_fn=serial.serial_ok,
    get_lamp_fn=get_lamp_state,
)
_async_emit = socket_mgr.async_emit
socket_mgr.start()
configure_emit(_async_emit)

if socket_mgr.wait_until_connected():
    print("~ 1 Dashboard SocketIO connected")
else:
    print("~ 1 Dashboard SocketIO not connected — errors will queue")

error_mgr = get_error_manager(_async_emit)
# ── Load NCNN model 
net = ncnn.Net()
net.opt.num_threads         = 4
net.opt.use_fp16_packed     = True
net.opt.use_fp16_storage    = True
net.opt.use_fp16_arithmetic = True
net.opt.use_packing_layout  = True

if net.load_param(param_file) != 0:
    error_mgr.raise_error("MODEL_LOAD_FAILED", {
        "stage": "load_param",
        "file": param_file,
        "model": Yolo_model,
    })
    time.sleep(1.0)
    raise RuntimeError(f"Failed to load PARAM: {param_file}")
if net.load_model(bin_file) != 0:
    error_mgr.raise_error("MODEL_LOAD_FAILED", {
        "stage": "load_bin",
        "file": bin_file,
        "model": Yolo_model,
    })
    time.sleep(1.0)
    raise RuntimeError(f"Failed to load BIN: {bin_file}")
error_mgr.resolve_error("MODEL_LOAD_FAILED")
print("~ 2 Model loaded OK")

# ── Camera 
picam = Picamera2()
picam.configure(picam.create_video_configuration(main={"size": (input_size, input_size), "format": "RGB888"}))
picam.set_controls({"AeEnable": False,"AnalogueGain": 3,"ExposureTime": 10000,}) # camera ISP settings

 #Wider FOV: crop the full sensor width into a square, then scale to input_size
sensor_w, sensor_h = picam.sensor_resolution
crop_size = min(sensor_w, sensor_h)   # largest square = widest FOV
x = (sensor_w - crop_size) // 2
y = (sensor_h - crop_size) // 2
picam.set_controls({"ScalerCrop": (x, y, crop_size, crop_size)})

picam.start()
print("~ 3 Camera OK")

# ── Connect Serial after ErrorManager is ready 
serial.connect(port=PORT, emit_fn=_async_emit)
print("~ 4 Serial connection attempted")

# ── Active servo state 
active_servo       = None
active_servo_lock  = threading.Lock()
active_servo_until = 0.0

def _get_active_servo():
    with active_servo_lock:
        return active_servo, active_servo_until

def _set_active_servo(category, until_ts):
    global active_servo, active_servo_until
    with active_servo_lock:
        active_servo       = category
        active_servo_until = until_ts

# ── Buffer Manager 
buf_mgr = BufferManager(
    min_frames       = min_frames,
    gap_limit        = gap_limit,
    emit_fn          = _async_emit,
    serial_send_fn   = serial.send,
    get_active_servo = _get_active_servo,
    set_active_servo = _set_active_servo,
)
configure_buffer_manager(buf_mgr)

# ── Serial reader thread 
threading.Thread(
    target=serial_reader,
    kwargs={
        "serial_manager": serial,
        "emit_fn": _async_emit,
        "servo_index_to_category": SERVO_INDEX_TO_CATEGORY,
        "set_active_servo": _set_active_servo,
        "set_conveyor_state": _set_conveyor_state,
    },
    daemon=True,
).start()

# ── Non-Maximum Suppression
def nms(boxes, scores, threshold):
    if len(boxes) == 0:
        return []
    boxes  = np.array(boxes,  dtype=np.float32)
    scores = np.array(scores, dtype=np.float32)
    x1, y1 = boxes[:,0], boxes[:,1]
    x2, y2 = boxes[:,2], boxes[:,3]
    areas  = (x2 - x1) * (y2 - y1)
    order  = scores.argsort()[::-1]
    keep   = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w   = np.maximum(0.0, xx2 - xx1)
        h   = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr   = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[np.where(ovr <= threshold)[0] + 1]
    return keep

# ── Encoder thread (WebSocket) 

encoder_running = True
latest_frame = None
frame_lock   = threading.Lock()
encoded_buf  = None
encoded_seq  = 0          
encoded_lock = threading.Lock()
encode_event = threading.Event()

STREAM_WIDTH   = 480
STREAM_HEIGHT  = 320
STREAM_QUALITY = 35       # JPEG quality implicitto reduced  for speed

def encoder_thread_fn():
    """Runs in a background thread. Waits for a signal 
    (encode_event) that a new frame is ready, then resizes 
    it and compresses it at a quality 35"""
    global encoded_buf, encoded_seq
    while encoder_running:
        encode_event.wait(timeout=0.1)
        encode_event.clear()
        with frame_lock:
            frame = latest_frame
        if frame is None:
            continue
        stream_frame = cv2.resize(frame, (STREAM_WIDTH, STREAM_HEIGHT))
        _, buf_jpg = cv2.imencode('.jpg', stream_frame,
            [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY,cv2.IMWRITE_JPEG_OPTIMIZE, 1]   # slightly smaller file      
            )
        with encoded_lock:
            encoded_buf = buf_jpg.tobytes()
            encoded_seq += 1                 # ← signal that a new frame is ready

threading.Thread(target=encoder_thread_fn, daemon=True).start()

# ── WebSocket server 
async def yolo_handler(ws):
    print(f"WS client: {ws.remote_address}")
    last_sent_seq = -1   # ← track which seq this client last received
    try:
        while True:
            with encoded_lock:
                data = encoded_buf
                seq  = encoded_seq
            if data and seq != last_sent_seq:
                try:
                    await asyncio.wait_for(ws.send(data), timeout=0.10)
                    last_sent_seq = seq
                except asyncio.TimeoutError:
                    pass

            await asyncio.sleep(0.033)  
    except websockets.exceptions.ConnectionClosed:
        pass

async def run_ws_server():
    print("WebSocket stream on ws://0.0.0.0:8765")
    async with websockets.serve(yolo_handler, "0.0.0.0", 8765):
        await asyncio.Future()

threading.Thread(target=lambda: asyncio.run(run_ws_server()), daemon=True).start()

# ── Main inference loop 

fps_buffer = []
prev_t     = None

try:
    while True:
        loop_start = time.time()
        frame = picam.capture_array()
        h0, w0 = frame.shape[:2]
        # ── NCNN inference 
        frame_resized = cv2.resize(frame, (input_size, input_size))
        frame_resized = np.ascontiguousarray(frame_resized)

        mat = ncnn.Mat.from_pixels(frame_resized,ncnn.Mat.PixelType.PIXEL_RGB,input_size,input_size,)
        mat.substract_mean_normalize([0, 0, 0], [1/255.0] * 3)

        ex = net.create_extractor()
        ex.input("in0", mat)
        ret, out = ex.extract("out0")
        del ex

        if ret != 0:
            continue

        data = out.numpy().T.copy()
        del out

        cx, cy, bw, bh = data[:,0], data[:,1], data[:,2], data[:,3]
        class_scores   = data[:,4:4+num_classes]
        confs = class_scores.max(axis=1)
        cids  = class_scores.argmax(axis=1)
        mask  = confs >= conf_thresh

        detections = []
        if mask.any():
            sx, sy = w0/input_size, h0/input_size
            x1s = np.clip(((cx[mask] - bw[mask]/2) * sx).astype(int), 0, w0-1)
            y1s = np.clip(((cy[mask] - bh[mask]/2) * sy).astype(int), 0, h0-1)
            x2s = np.clip(((cx[mask] + bw[mask]/2) * sx).astype(int), 0, w0-1)
            y2s = np.clip(((cy[mask] + bh[mask]/2) * sy).astype(int), 0, h0-1)
            detections = list(zip(x1s, y1s, x2s, y2s, confs[mask], cids[mask]))
            keep = nms(
                [[d[0], d[1], d[2], d[3]] for d in detections],
                [d[4] for d in detections],
                nms_thresh,
            )
            detections = [detections[i] for i in keep]

        # ── Feed buffer 
        if detections:
            best = max(detections, key=lambda d: d[4])
            cid  = int(best[5])
            cat  = LABEL_TO_CATEGORY.get(cid, "unrecognized").lower()
            buf_mgr.add(cat, weight=float(best[4]))
        else:
            buf_mgr.no_detection()

        # ── Detection draw 
        for d in detections:
            x1, y1, x2, y2, conf, cid = d
            cid = int(cid)
            color = bbox_colors[cid % len(bbox_colors)]
            cat   = LABEL_TO_CATEGORY.get(cid, "?").lower()
            lbl   = f"{labels[cid]} [{cat}] {int(conf*100)}%"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, lbl, (x1, max(y1-5, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # ── Buffer overlay  
        collecting, votes_snap, gap_snap = buf_mgr.snapshot()
        if collecting:
            c_snap = Counter(votes_snap)
            total  = len(votes_snap)
            y_off  = 60
            for cat, n in c_snap.most_common():
                y_off += 22
                pct = int(n/total*100) if total else 0
                cv2.putText(frame, f"  {cat}: {n} ({pct}%)",(10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,255,200), 1)

        # ── FPS counter 
        elapsed = time.time() - loop_start
        now = time.time()
        if prev_t is not None:
            fps_buffer.append(1.0 / max(now - prev_t, 1e-6))
            if len(fps_buffer) > 30:
                fps_buffer.pop(0)
        prev_t = now
        avg_fps = sum(fps_buffer) / len(fps_buffer) if fps_buffer else 0.0
        cv2.putText(frame, f"FPS: {avg_fps:.1f}",(10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0,255,255), 1)

        # ── Push clean frame to WebSocket encoder 
        with frame_lock:
            latest_frame = frame.copy()
        encode_event.set()

except KeyboardInterrupt:
    pass
finally:
    encoder_running = False
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN) 
    print("Stopping…")
    picam.close()
    if serial:
        serial.close()