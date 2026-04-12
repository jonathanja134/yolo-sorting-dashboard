"""
yolo_reader.py – YOLO inference + adaptive majority-vote buffer
                  + serial protocol (Pi ↔ Arduino) + SocketIO → Flask
                  + WebSocket MJPEG stream + local cv2 display

Servo / category mapping (canonical across all files):
  canister   → Servo 1 – pin 13
  sharps     → Servo 2 – pin 12
  applicator → Servo 3 – pin 8
  inhaler    → Servo 4 – pin 7

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

import gc
gc.disable()

import serial
import os
import argparse
import ncnn
import cv2
import numpy as np
import time
import threading
import socketio
import asyncio
import websockets
from collections import Counter
from picamera2 import Picamera2
import queue

# ── CLI args ────────────────────────────────────────────────────────────────── OK
parser = argparse.ArgumentParser()
parser.add_argument('--model', default='yolo11n', help='Model folder')
parser.add_argument('--serial-port', default='/dev/ttyACM0', dest='serial_port')
parser.add_argument('--baud', default=9600, type=int)
parser.add_argument('--server-url', default='http://localhost:5000', dest='server_url')
parser.add_argument('--min-frames', default=5, type=int, dest='min_frames', help='Minimum detections before committing a label')
parser.add_argument('--gap-limit', default=20, type=int, dest='gap_limit', help='Consecutive empty frames before auto-commit')
args = parser.parse_args()

# ── Model paths ─────────────────────────────────────────────────────────────── OK
script_dir = os.path.dirname(os.path.abspath(__file__))
model_dir  = os.path.join(script_dir, "my_model_ncnn_model", args.model)
param_file = os.path.join(model_dir, "model.ncnn.param")
bin_file   = os.path.join(model_dir, "model.ncnn.bin")

# ── Inference config ────────────────────────────────────────────────────────── OK
input_size  = 640
conf_thresh = 0.6
nms_thresh  = 0.45

# ── Labels ──────────────────────────────────────────────────────────────────── OK
labels = [
    "Applicator white/blue",   # 0
    "Applicator white/gray",   # 1
    "Applicator gray",         # 2
    "Applicator orange/white", # 3
    "Applicator pink",         # 4
    "Inhaler blue",            # 5
    "Inhaler white",           # 6
    "Canister"                 # 7
    # Sharps: label index TBD — future YOLO model
]

bbox_colors = [(173, 216, 230),(211, 211, 211),(105, 105, 105),(255, 165,   0), (255, 192, 203), (  0,   0, 128),(255, 255, 255), (255,   0,   0)]

# ── Canonical category mapping ────────────────────────────────────────────────

# YOLO label index → Category
LABEL_TO_CATEGORY = {
    0: "applicator",
    1: "applicator",
    2: "applicator",
    3: "applicator",
    4: "applicator",
    5: "inhaler",
    6: "inhaler",
    7: "canister",
    # sharps: no label index yet — add here when new YOLO model is ready
}

# Arduino servo index → Category
SERVO_INDEX_TO_CATEGORY = {
    1: "canister",
    2: "sharps",
    3: "applicator",
    4: "inhaler",
}
# Category → Servo Label
SERVO_LABEL = {
    "canister":   "Servo 1 – Canister",
    "sharps":     "Servo 2 – Sharps / Apply Pen / Syringes / Bag",
    "applicator": "Servo 3 – Applicator",
    "inhaler":    "Servo 4 – Inhaler",
}
# Category → Servo color ( RGB )
SERVO_COLOR = {
    "canister":   (  0, 200, 255), #
    "sharps":     (  0,  80, 255),
    "applicator": (200, 255,  80),
    "inhaler":    ( 80, 255, 200),
}

num_classes = len(labels)

# ── Load NCNN model ─────────────────────────────────────────────────────────── OK
net = ncnn.Net()
net.opt.use_vulkan_compute  = False
net.opt.num_threads         = 4
net.opt.use_fp16_packed     = True
net.opt.use_fp16_storage    = True
net.opt.use_fp16_arithmetic = True
net.opt.use_packing_layout  = True

if net.load_param(param_file) != 0:
    raise RuntimeError(f"Failed to load param: {param_file}")
if net.load_model(bin_file) != 0:
    raise RuntimeError(f"Failed to load model: {bin_file}")
print("Model loaded OK")

# ── Camera ──────────────────────────────────────────────────────────────────── OK
picam = Picamera2()
picam.configure(picam.create_video_configuration(
    main={"size": (input_size, input_size), "format": "RGB888"}
))
picam.start()
print("Camera OK")

# ── Serial (Pi ↔ Arduino) ───────────────────────────────────────────────────── OK
try:
    ser = serial.Serial(args.serial_port, args.baud, timeout=0.05)
    print(f"Serial OK on {args.serial_port} @ {args.baud}")
except Exception as e:
    ser = None
    print(f"Serial UNAVAILABLE ({e}) — running without Arduino")

def serial_send(msg: str):
    if ser and ser.is_open:
        ser.write((msg + "\n").encode())
        print(f"[SERIAL →] {msg}")

# ── Conveyor motor state ────────────────────────────────────────────────────── OK
motor_running = False
motor_lock    = threading.Lock()

# ── SocketIO client ─────────────────────────────────────────────────────────── OK
sio = socketio.Client(reconnection=True, reconnection_attempts=0)

# ── Emit initial state when SocketIO connects ───────────────────────────────── OK
@sio.on("connect")
def on_sio_connect():
    print("[SIO] connected — emitting initial conveyor state")
    with motor_lock:
        running = motor_running
    _async_emit("conveyor_state", {
        "id":      "conveyor_1",
        "running": running,
    })

def connect_socketio():
    while True:
        try:
            sio.connect(args.server_url) # no use of transports=["polling"]
            print(f"SocketIO connected to {args.server_url} ({sio.transport()})")
            sio.emit("test_latency", {"t": time.time()}) # latency test send 
            break
        except Exception as e:
            print(f"SocketIO connect failed ({e}), retrying…")
            time.sleep(3)

threading.Thread(target=connect_socketio, daemon=True).start()

# ── SocketIO latency test response handler ─────────────────────────────────── OK

@sio.on("latency_reply")
def on_latency_reply(data):
    dt = time.time() - data["t"]
    print(f"Latency: {dt*1000:.1f} ms")

# ── Conveyor control from dashboard ────────────────────────────────────────── OK

@sio.on("update_conveyor")
def on_conveyor_update(data):
    global motor_running
    requested = bool(data.get("running", False))

    with motor_lock:
        if requested == motor_running:
            return
        motor_running = requested 

    cmd = "MOTOR:FORWARD" if requested else "MOTOR:STOP"
    serial_send(cmd)

    print(f"[DASHBOARD → YOLO] Request: {'RUNNING' if requested else 'STOP'}")

# ── Shared frame buffers (for WebSocket encoder) ────────────────────────────── OK

latest_frame = None
frame_lock   = threading.Lock()
encoded_buf  = None
encoded_lock = threading.Lock()
encode_event = threading.Event()

# ── Active servo state ──────────────────────────────────────────────────────── OK
active_servo       = None
active_servo_lock  = threading.Lock()
active_servo_until = 0.0

# ── Adaptive majority-vote buffer ───────────────────────────────────────────── OK
MIN_FRAMES = args.min_frames
GAP_LIMIT  = args.gap_limit

class DetectionBuffer:
    def __init__(self):
        self.votes = []
        self.gap_counter = 0
        self.collecting = False

    def reset(self):
        self.votes = []
        self.gap_counter = 0
        self.collecting = True
        print("[BUFFER] reset — collecting")
        _emit_buffer_state(self)

    def add(self, category: str, weight: float = 1.0):
        self.votes.append((category, weight))
        self.gap_counter = 0
        _emit_buffer_state(self)

    def no_detection(self):
        if not self.collecting:
            return
        self.gap_counter += 1
        _emit_buffer_state(self)
        if self.gap_counter >= GAP_LIMIT:
            print("[BUFFER] gap limit reached — auto-commit")
            self.collecting = False
            _trigger_commit()

    def commit(self):
        result = _compute_result(self.votes)
        self.collecting = False
        self.gap_counter = 0
        return result

    def stop(self):
        self.collecting = False

buf      = DetectionBuffer()
buf_lock = threading.Lock()

# ── Non-blocking emit queue ───────────────────────────────────────────────────
_emit_queue = queue.Queue()

def _emit_worker():
    while True:
        event, data = _emit_queue.get()
        try:
            if sio.connected:
                sio.emit(event, data)
        except Exception as e:
            print(f"[EMIT] error: {e}")
        finally:
            _emit_queue.task_done()

threading.Thread(target=_emit_worker, daemon=True).start()

def _async_emit(event, data):
    _emit_queue.put_nowait((event, data))

def _trigger_commit():
    threading.Thread(target=commit_buffer, daemon=True).start()

def _compute_result(votes):
    if not votes:
        return None
    c = Counter()
    total_weight = 0.0
    for cat, w in votes:
        c[cat] += w
        total_weight += w
    winner, top_weight = c.most_common(1)[0]
    breakdown = {cat: {"count": n, "pct": round(n / total_weight * 100)}
                 for cat, n in c.most_common()}
    return {
        "winner":         winner,
        "confidence":     round(top_weight / total_weight, 3),
        "total_frames":   len(votes),
        "breakdown":      breakdown,
        "low_confidence": len(votes) < MIN_FRAMES,
    }

def _emit_buffer_state(b):
    result = _compute_result(b.votes) if b.votes else None
    _async_emit("buffer_update", {
        "collecting":   b.collecting,
        "total_frames": len(b.votes),
        "min_frames":   MIN_FRAMES,
        "gap_counter":  b.gap_counter,
        "gap_limit":    GAP_LIMIT,
        "breakdown":    result["breakdown"] if result else {},
        "leader":       result["winner"]    if result else None,
    })

def commit_buffer():
    global active_servo, active_servo_until
    with buf_lock:
        result = buf.commit()
    if result is None:
        print("[COMMIT] empty buffer — skipped")
        return
    print(f"[COMMIT] {result}")

    if result["low_confidence"]:
        print("[COMMIT] low confidence")
        _async_emit("yolo_detection", {
            "label":        "unrecognized",
            "confidence":   result["confidence"],
            "display":      f"Low confidence ({result['total_frames']} frames)",
            "breakdown":    result["breakdown"],
            "total_frames": result["total_frames"],
        })
        return

    category   = result["winner"]
    confidence = result["confidence"]
    display    = category.capitalize()

    # Overlay shown until Arduino confirms close (or 10s safety cap)
    with active_servo_lock:
        active_servo = category
        active_servo_until = time.time() + 10.0   # safety cap; cleared on CLOSED feedback

    serial_send(f"LABEL:{category}")

    _async_emit("servo_update", {
        "type": category, 
        "active": True
        })
    _async_emit("yolo_detection", {
        "label":        category,
        "confidence":   confidence,
        "display":      display,
        "breakdown":    result["breakdown"],
        "total_frames": result["total_frames"],
    })
    _async_emit("buffer_update", {
        "collecting":   False,
        "committed":    True,
        "winner":       category,
        "confidence":   confidence,
        "total_frames": result["total_frames"],
        "min_frames":   MIN_FRAMES,
        "gap_counter":  0,
        "gap_limit":    GAP_LIMIT,
        "breakdown":    result["breakdown"],
        "leader":       category,
    })

# ── STATUS line parser ────────────────────────────────────────────────────────
def _handle_status_line(line: str):
    """
    Parse STATUS:MOTOR:FORWARD|SENSOR1:CLEAR|... and emit a snapshot
    so the dashboard can sync state after any Arduino change.
    """
    content = line[7:]          # strip "STATUS:"
    snapshot = {}
    for token in content.split("|"):
        kv = token.split(":", 1)
        if len(kv) == 2:
            snapshot[kv[0]] = kv[1]
    _async_emit("status_snapshot", snapshot)

# ── Serial reader — handles EVERY Arduino message type ───────────────────────
def serial_reader():
    while True:
        if not ser or not ser.is_open:
            time.sleep(0.1)
            continue
        try:
            raw  = ser.readline().decode(errors="ignore").strip()
            line = raw
            if not line:
                continue

            print(f"[SERIAL ←] {line}")

            # ── Separator lines ───────────────────────────────────────────────
            if line.startswith("---"):
                continue

            # ── STATUS snapshot ───────────────────────────────────────────────
            if line.startswith("STATUS:"):
                _handle_status_line(line)
                continue

            # ── CHANGE annotation (log only) ──────────────────────────────────
            if line.startswith("CHANGE:"):
                _async_emit("change_event", {"change": line[7:]})
                continue

            parts = line.split(":")

            # ── Sensor events → buffer + dashboard ───────────────────────────
            if len(parts) == 3 and parts[0] == "SENSOR":
                sensor_id = parts[1]
                event     = parts[2]

                # ── RESET: commit previous, start fresh ──────────────────
                if sensor_id == "RESET" and event == "TRIGGERED":
                    with buf_lock:
                        has_enough     = len(buf.votes) >= MIN_FRAMES
                        was_collecting = buf.collecting
                        buf.collecting = False

                    if was_collecting and has_enough:
                        print(f"[BUFFER] reset → committing {len(buf.votes)} frames")
                        _trigger_commit()
                    else:
                        print(f"[BUFFER] reset → skipping ({len(buf.votes)}/{MIN_FRAMES} frames)")

                    with buf_lock:
                        buf.reset()
                    continue
                
                # ── POS_SENSOR 1 & 2: dashboard only ─────────────────────
                _async_emit("sensor_update", {
                    "id":          f"sensor_{sensor_id}",
                    "triggered":   event == "TRIGGERED",
                    "distance_cm": None,
                })
                continue

            # ── Motor ACK → update conveyor state on dashboard ────────────────
            if len(parts) == 3 and parts[0] == "ACK" and parts[1] == "MOTOR":
                running = parts[2] == "FORWARD"

                with motor_lock:
                    global motor_running
                    motor_running = running   # ✅ THIS WAS MISSING

                print(f"[ARDUINO → YOLO] Motor state = {'RUNNING' if running else 'STOP'}")

                _async_emit("conveyor_state", {
                    "id":      "conveyor_1",
                    "running": running,
                })
                continue

            # ── Label ACK ────────────────────────────────────────────────────
            if len(parts) == 3 and parts[0] == "ACK" and parts[1] == "LABEL":
                category = parts[2].lower()
                _async_emit("ack_label", {"category": category})
                continue

            # ── Servo events ──────────────────────────────────────────────────
            if len(parts) >= 3 and parts[0] == "SERVO":
                try:
                    servo_idx = int(parts[1])
                    event     = parts[2]
                except (ValueError, IndexError):
                    _async_emit("arduino_error", {
                        "error": f"SERVO parse error: {line}",
                        "raw":   line,
                    })
                    continue

                category = SERVO_INDEX_TO_CATEGORY.get(servo_idx)
                if category is None:
                    _async_emit("arduino_error", {
                        "error": f"Unknown servo index {servo_idx}",
                        "raw":   line,
                    })
                    continue

                if event == "OPEN":
                    # Arduino confirmed open — dashboard already notified by
                    # servo_update(active=True) sent from commit_buffer.
                    # Nothing extra needed; OBJECT_DETECTED is informational.
                    pass

                elif event == "OBJECT_DETECTED":
                    # Informational only — relay for dashboard log
                    _async_emit("servo_object_detected", {
                        "type":  category,
                        "index": servo_idx,
                    })

                elif event in ("CLOSED_OK", "CLOSED_TIMEOUT"):
                    # ─── PRIMARY servo deactivation path ───────────────────
                    # Driven entirely by Arduino feedback, no timers.
                    with active_servo_lock:
                        global active_servo, active_servo_until
                        if active_servo == category:
                            active_servo       = None
                            active_servo_until = 0.0
                    _async_emit("servo_closed", {
                        "type":   category,
                        "index":  servo_idx,
                        "status": event.lower(),   # "closed_ok" or "closed_timeout"
                    })

                elif event == "BLOCKED":
                    _async_emit("servo_error", {
                        "type":  category,
                        "index": servo_idx,
                        "error": "blocked_at_start",
                    })

                continue

            # ── ERR messages → relay to dashboard ────────────────────────────
            if parts[0] == "ERR":
                detail = ":".join(parts[1:])
                _async_emit("arduino_error", {
                    "error": detail,
                    "raw":   line,
                })
                continue

            # ── INFO messages (e.g. INFO:UNRECOGNIZED) ────────────────────────
            if parts[0] == "INFO":
                detail = ":".join(parts[1:])
                _async_emit("arduino_info", {
                    "info": detail,
                    "raw":  line,
                })
                continue

            # ── Boot/ready banner — ignore ────────────────────────────────────
            if "Sorting System Ready" in line:
                continue

            # ── Anything unrecognised — log as warning ────────────────────────
            _async_emit("arduino_error", {
                "error": f"Unrecognised serial line: {line}",
                "raw":   line,
            })

        except Exception as e:
            print(f"[SERIAL] read error: {e}")
            time.sleep(0.05)

threading.Thread(target=serial_reader, daemon=True).start()

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

# ── Keyboard sensor simulation ────────────────────────────────────────────────
def kb_sensor_triggered():
    print("[KB SIM] SENSOR TRIGGERED")
    _async_emit("sensor_update", {
        "id": "sensor_1", "triggered": True, "distance_cm": None
    })
    with buf_lock:
        buf.reset()

def kb_sensor_clear():
    print("[KB SIM] SENSOR CLEAR")
    _async_emit("sensor_update", {
        "id": "sensor_1", "triggered": False, "distance_cm": None
    })
    with buf_lock:
        if buf.collecting:
            buf.collecting = False
            _trigger_commit()

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
fps_buffer = []
prev_t     = None

print("Inference running — SPACE=sensor trigger  C=sensor clear  Q=quit")

try:
    while True:
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

        with buf_lock:
            if buf.collecting:
                if detections:
                    best = max(detections, key=lambda d: d[4])
                    cid  = int(best[5])
                    cat  = LABEL_TO_CATEGORY.get(cid, "unrecognized")
                    buf.add(cat, weight=float(best[4]))
                else:
                    buf.no_detection()

        # ── Draw detections ───────────────────────────────────────────────────
        for d in detections:
            x1, y1, x2, y2, conf, cid = d
            cid   = int(cid)
            color = bbox_colors[cid % len(bbox_colors)]
            cat   = LABEL_TO_CATEGORY.get(cid, "?")
            lbl   = f"{labels[cid]} [{cat}] {int(conf*100)}%"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, lbl, (x1, max(y1-5, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # ── Buffer overlay ────────────────────────────────────────────────────
        with buf_lock:
            collecting = buf.collecting
            votes_snap = [v[0] for v in buf.votes]
            gap_snap   = buf.gap_counter

        if collecting:
            c_snap = Counter(votes_snap)
            total  = len(votes_snap)
            y_off  = 60
            cv2.putText(frame,
                        f"BUFFER: {total} frames  gap:{gap_snap}/{GAP_LIMIT}",
                        (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,255), 2)
            for cat, n in c_snap.most_common():
                y_off += 22
                pct = int(n/total*100) if total else 0
                cv2.putText(frame, f"  {cat}: {n} ({pct}%)",
                            (10, y_off), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,255,200), 1)

        # ── Keyboard hint overlay ─────────────────────────────────────────────
        cv2.putText(frame, "SPACE=trigger  C=clear  Q=quit",
                    (10, input_size - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)

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
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,255), 2)

        # ── Push to WebSocket encoder ─────────────────────────────────────────
        with frame_lock:
            latest_frame = frame.copy()
        encode_event.set()

        # ── Local display + keyboard input ────────────────────────────────────
        cv2.imshow("YOLO", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '):
            kb_sensor_triggered()
        elif key == ord('c'):
            kb_sensor_clear()

except KeyboardInterrupt:
    pass

finally:
    encoder_running = False
    cv2.destroyAllWindows()
    print("Stopping…")
    picam.close()
    if ser:
        ser.close()