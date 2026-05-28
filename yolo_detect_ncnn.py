"""
yolo_reader.py – YOLO inference + adaptive majority-vote buffer TEST
                  + serial protocol (Pi ↔ Arduino) + SocketIO → Flask
                  + WebSocket MJPEG stream + local cv2 display

Servo / category mapping (canonical across all files):
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
  STATUS:MOTOR:...|SENSOR1:...|SENSOR2:...|SERVO1:..|SERVO2:..|SERVO3:..|SERVO4:..
  CHANGE:<what changed>
  ---------------------   (separator lines – ignored)
"""
import serial,os,argparse,numpy as np,time
import ncnn,cv2,threading,asyncio,websockets 
from collections import Counter
from picamera2 import Picamera2
from ProgramManager.KeyboardSimulation import kb_sensor_triggered,kb_sensor_clear,configure_buffer_manager
from ProgramManager.event_bus import configure_emit, _async_emit
from ProgramManager.serialManager import SerialManager, serial_reader
from ProgramManager.socketManager import SocketManager
from ProgramManager.Buffer import BufferManager
from ProgramManager.config import labels,num_classes,bbox_colors,LABEL_TO_CATEGORY,SERVO_INDEX_TO_CATEGORY,SERVO_LABEL,SERVO_COLOR,BAUD,PORT,input_size,conf_thresh,nms_thresh,min_frames,gap_limit
from ProgramManager.ErrorManager import (
    get_error_manager,
    ErrorSeverity,
    ErrorSource,
)

# ── CLI args ────────────────────────────────────────────────────────────────── OK
parser = argparse.ArgumentParser()
parser.add_argument('--model', default='yolo26nV3', help='Model (yolo11n , yolo26nV3, yolo11s)')
parser.add_argument('--min-frames', default=20, type=int, dest='min_frames', help='Minimum detections before committing a label')
parser.add_argument('--gap-limit', default=20, type=int, dest='gap_limit', help='Consecutive empty frames before auto-commit')
args = parser.parse_args()

# ── Model paths ─────────────────────────────────────────────────────────────── OK
script_dir = os.path.dirname(os.path.abspath(__file__))
model_dir  = os.path.join(script_dir, "my_model_ncnn_model", args.model)
param_file = os.path.join(model_dir, "model.ncnn.param")
bin_file   = os.path.join(model_dir, "model.ncnn.bin")

# ── Load NCNN model ─────────────────────────────────────────────────────────── OK
net = ncnn.Net()
net.opt.num_threads         = 4
net.opt.use_fp16_packed     = True
net.opt.use_fp16_storage    = True
net.opt.use_fp16_arithmetic = True
net.opt.use_packing_layout  = True

if net.load_param(param_file) != 0:
    get_error_manager.raise_error(
            "MODEL_LOAD_FAILED",
            {
                "stage": "load_param",
                "file": param_file,
                "model": args.model,
            }
        )
    raise RuntimeError(f"Failed to load PARAM: {param_file}")
if net.load_model(bin_file) != 0:
    get_error_manager.raise_error(
            "MODEL_LOAD_FAILED",
            {
                "stage": "load_bin",
                "file": bin_file,
                "model": args.model,
            }
        )
    raise RuntimeError(f"Failed to load BIN: {bin_file}")
get_error_manager.resolve_error("MODEL_LOAD_FAILED")
print("|1| Model loaded OK")

# ── Camera ──────────────────────────────────────────────────────────────────── OK
picam = Picamera2()
picam.configure(picam.create_video_configuration(
    main={"size": (input_size, input_size), "format": "RGB888"}
))
picam.start()
print("|2| Camera OK")

# ── Serial (Pi ↔ Arduino) ───────────────────────────────────────────────────── OK
serial = SerialManager(baud=BAUD)
print("|3| Serial Manager created")

# ── Conveyor motor states (3 separate conveyors) ─────────────────────────────

# Conveyor 1: Pin 10
motor_1_running = False
motor_1_lock    = threading.Lock()

# Conveyor 2: Pin 9
motor_2_running = False
motor_2_lock    = threading.Lock()

# Conveyor 3: Pin 8
motor_3_running = False
motor_3_lock    = threading.Lock()

# All conveyor states in one dict
def _get_multi_conveyor_states():
    """Return {conveyor_1: bool, conveyor_2: bool, conveyor_3: bool}"""
    with motor_1_lock, motor_2_lock, motor_3_lock:
        return {
            "conveyor_1": motor_1_running,
            "conveyor_2": motor_2_running,
            "conveyor_3": motor_3_running,
        }

def _set_multi_conveyor_state(conv_id, running):
    """Set state for a specific conveyor by ID"""
    global motor_1_running, motor_2_running, motor_3_running
    if conv_id == "conveyor_1":
        with motor_1_lock:
            motor_1_running = running
    elif conv_id == "conveyor_2":
        with motor_2_lock:
            motor_2_running = running
    elif conv_id == "conveyor_3":
        with motor_3_lock:
            motor_3_running = running

# Legacy single-conveyor accessors (conveyor_1 only) for backward compatibility
def _get_motor_running():
    with motor_1_lock:
        return motor_1_running

def _set_motor_running(running):
    global motor_1_running
    with motor_1_lock:
        motor_1_running = running

# ── SocketIO Manager ─────────────────────────────────────────────────────
socket_mgr = SocketManager(
    server_url="http://localhost:5000",
    get_motor_running_fn=_get_motor_running,                # Legacy
    set_motor_running_fn=_set_motor_running,                # Legacy
    get_multi_conveyor_fn=_get_multi_conveyor_states,       # New multi-conveyor
    set_multi_conveyor_fn=_set_multi_conveyor_state,        # New multi-conveyor
    serial_send_fn=serial.send,
    emit_fn=_async_emit,                                    # For error reporting
)
_async_emit = socket_mgr.async_emit
socket_mgr.start()
configure_emit(_async_emit)

# ── Error Manager ────────────────────────────────────────────────────────────
error_mgr = get_error_manager(_async_emit)
print("|3.5| Error Manager initialized")

# ── Connect Serial after ErrorManager is ready ────────────────────────────────
serial.connect(port=PORT, emit_fn=_async_emit)
print("|3.6| Serial connection attempted")

# ── Active servo state ──────────────────────────────────────────────────────── OK
active_servo       = None
active_servo_lock  = threading.Lock()
active_servo_until = 0.0

# ── Active servo accessors (injected into BufferManager) ─────────────────────
def _get_active_servo():
    with active_servo_lock:
        return active_servo, active_servo_until

def _set_active_servo(category, until_ts):
    global active_servo, active_servo_until
    with active_servo_lock:
        active_servo       = category
        active_servo_until = until_ts

# ── Buffer Manager ─────────────────────────────────────────────────────────────
buf_mgr = BufferManager(
    min_frames       = args.min_frames,
    gap_limit        = args.gap_limit,
    emit_fn          = _async_emit,
    serial_send_fn   = serial.send,
    get_active_servo = _get_active_servo,
    set_active_servo = _set_active_servo,
)
configure_buffer_manager(buf_mgr)

# ── Serial reader thread ───────────────────────────────────────────────────────

threading.Thread(
    target=serial_reader,
    kwargs={
        "serial_manager": serial,
        "emit_fn": _async_emit,
        "buffer_manager": buf_mgr,
        "motor_state_setter": _set_motor_running,
        "servo_index_to_category": SERVO_INDEX_TO_CATEGORY,
        "set_active_servo": _set_active_servo,
        "multi_motor_state_setter": _set_multi_conveyor_state,  # New: support 3 conveyors
    },
    daemon=True,
).start()

# ── NMS ───────────────────────────────────────────────────────────────────────
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

# ── Encoder thread (WebSocket) ────────────────────────────────────────────────
encoder_running = True
latest_frame = None
frame_lock   = threading.Lock()
encoded_buf  = None
encoded_lock = threading.Lock()
encode_event = threading.Event()

def encoder_thread_fn():
    global encoded_buf
    while encoder_running:
        encode_event.wait(timeout=0.1)
        encode_event.clear()
        with frame_lock:
            frame = latest_frame
        if frame is None:
            continue
        _, buf_jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        with encoded_lock:
            encoded_buf = buf_jpg.tobytes()

threading.Thread(target=encoder_thread_fn, daemon=True).start()

# ── WebSocket server ──────────────────────────────────────────────────────────
async def yolo_handler(ws):
    print(f"WS client: {ws.remote_address}")
    try:
        while True:
            with encoded_lock:
                data = encoded_buf
            if data:
                await ws.send(data)
            await asyncio.sleep(0.033)
    except websockets.exceptions.ConnectionClosed:
        pass

async def run_ws_server():
    print("WebSocket stream on ws://0.0.0.0:8765")
    async with websockets.serve(yolo_handler, "0.0.0.0", 8765):
        await asyncio.Future()

threading.Thread(target=lambda: asyncio.run(run_ws_server()), daemon=True).start()

# ── Servo overlay helper ──────────────────────────────────────────────────────
def draw_servo_overlay(frame):
    with active_servo_lock:
        cat   = active_servo
        until = active_servo_until

    if cat is None or time.time() > until:
        return

    color = SERVO_COLOR.get(cat, (200, 200, 200))
    label = SERVO_LABEL.get(cat, cat.capitalize())
    h, w  = frame.shape[:2]

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - 50), (w, h), color, -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
    cv2.putText(frame, f"ACTIVE: {label}",
                (12, h - 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

# ── Main inference loop ───────────────────────────────────────────────────────
# ── Frame-rate cap ────────────────────────────────────────────────────────────
TARGET_FPS      = 32
FRAME_BUDGET_S  = 1.0 / TARGET_FPS          # 0.0333 s per frame
fps_buffer = []
prev_t     = None

print("Inference running — SPACE=sensor trigger  C=sensor clear  Q=quit")

try:
    while True:
        loop_start = time.time()          # ← ADD THIS LINE
        try:
            frame = picam.capture_array()
        except Exception as e:
            print("Camera error:", e)
            continue

        h0, w0 = frame.shape[:2]

        # ── NCNN inference ────────────────────────────────────────────────────
        frame_resized = cv2.resize(frame, (input_size, input_size))
        frame_resized = np.ascontiguousarray(frame_resized)

        mat = ncnn.Mat.from_pixels(
            frame_resized,
            ncnn.Mat.PixelType.PIXEL_RGB,
            input_size,
            input_size
        )
        mat.substract_mean_normalize([0, 0, 0], [1/255.0] * 3)

        ex = net.create_extractor()
        ex.input("in0", mat)
        ret, out = ex.extract("out0")
        del ex

        if ret != 0:
            print("Inference error")
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
                nms_thresh
            )
            detections = [detections[i] for i in keep]

        # ── Feed buffer ───────────────────────────────────────────────────────
        if detections:
            best = max(detections, key=lambda d: d[4])
            cid  = int(best[5])
            cat  = LABEL_TO_CATEGORY.get(cid, "unrecognized").lower()
            buf_mgr.add(cat, weight=float(best[4]))
        else:
            buf_mgr.no_detection()
        # ── Draw detections ───────────────────────────────────────────────────
        for d in detections:
            x1, y1, x2, y2, conf, cid = d
            cid   = int(cid)
            color = bbox_colors[cid % len(bbox_colors)]
            cat   = LABEL_TO_CATEGORY.get(cid, "?").lower()
            lbl   = f"{labels[cid]} [{cat}] {int(conf*100)}%"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, lbl, (x1, max(y1-5, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        # ── Buffer overlay ────────────────────────────────────────────────────
        collecting, votes_snap, gap_snap = buf_mgr.snapshot()
        if collecting:
            c_snap = Counter(votes_snap)
            total  = len(votes_snap)
            y_off  = 60
            for cat, n in c_snap.most_common():
                y_off += 22
                pct = int(n/total*100) if total else 0
                cv2.putText(frame, f"  {cat}: {n} ({pct}%)",
                            (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,255,200), 1)
        # ── Keyboard hint overlay ─────────────────────────────────────────────
        #cv2.putText(frame, "SPACE=trigger  C=clear  Q=quit",
        #            (10, input_size - 10),
        #            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)
        # ── Active servo banner ───────────────────────────────────────────────
        draw_servo_overlay(frame)
        # ── FPS ───────────────────────────────────────────────────────────────
        now = time.time()
        if prev_t is not None:
            fps_buffer.append(1.0 / max(now - prev_t, 1e-6))
            if len(fps_buffer) > 30:
                fps_buffer.pop(0)
        prev_t = now
        avg_fps = sum(fps_buffer) / len(fps_buffer) if fps_buffer else 0.0
        cv2.putText(frame, f"FPS: {avg_fps:.1f}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)

        # ── Push to WebSocket encoder ─────────────────────────────────────────
        with frame_lock:
            latest_frame = frame.copy()
        encode_event.set()

        # ── Local display + keyboard input ────────────────────────────────────
        cv2.imshow("YOLO", frame)
        elapsed_before_wait = time.time() - loop_start
        wait_ms = max(1, int((FRAME_BUDGET_S - elapsed_before_wait) * 1000))
        key = cv2.waitKey(wait_ms) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '):
            kb_sensor_triggered()
        elif key == ord('c'):
            kb_sensor_clear()

        # ── 30 FPS cap ────────────────────────────────────────────────────────
        elapsed = time.time() - loop_start          # `now` already set above for FPS calc
        remainder = FRAME_BUDGET_S - elapsed
        if remainder > 0:
            time.sleep(remainder)

except KeyboardInterrupt:
    pass
finally:
    encoder_running = False
    cv2.destroyAllWindows()
    print("Stopping…")
    picam.close()

    if serial:
        serial.close()