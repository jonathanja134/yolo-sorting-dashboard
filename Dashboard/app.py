"""
app.py  –  Flask + SocketIO backend for the Sorting Control Dashboard.

Canonical servo / category mapping:
  canister   → Servo 1 – pin 13
  sharps     → Servo 2 – pin 12  (YOLO label TBD)
  applicator → Servo 3 – pin 8
  inhaler    → Servo 4 – pin 7

SocketIO events
───────────────
FROM frontend  →  control_conveyor
FROM Pi        →  servo_update        (active=True when label committed)
                  servo_closed        (active=False, driven by Arduino CLOSED_OK/TIMEOUT)
                  servo_error         (blocked_at_start, etc.)
                  servo_object_detected
                  sensor_update
                  yolo_detection
                  buffer_update
                  conveyor_state
                  arduino_error       (ERR:* lines from Arduino)
                  arduino_info        (INFO:* lines from Arduino)
                  ack_label           (ACK:LABEL:* from Arduino)
                  status_snapshot     (parsed STATUS: line)
                  change_event        (CHANGE: line)
TO   frontend  →  update_conveyor | update_servo | update_sensor
                  update_counts   | new_detection | unrecognized_alert
                  buffer_update   (relayed straight to browser)
                  servo_definitions (on connect)
                  system_error    (arduino errors → browser)
                  system_info
                  status_snapshot (relayed to browser)
"""

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
from Dashboard.Database import (
    init_db,
    get_conveyors, save_conveyor,
    get_servos,    save_servo,
    get_counts,    increment_count,
    get_unrecognized, increment_unrecognized,
    get_recent_events, get_session_start,
    log_event,
)
import datetime

app      = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

init_db()

# ── Canonical servo definitions ───────────────────────────────────────────────
SERVO_DEFINITIONS = {
    "canister":   {"label": "Servo 1 – Canister",                     "index": 1},
    "sharps":     {"label": "Servo 2 – Sharps / Apply Pen / Syringes","index": 2},
    "applicator": {"label": "Servo 3 – Applicator",                   "index": 3},
    "inhaler":    {"label": "Servo 4 – Inhaler",                      "index": 4},
}

KNOWN_CATEGORIES = set(SERVO_DEFINITIONS.keys())

# Categories stored in the event log — used by the filter UI
LOGGED_CATEGORIES = ["detection", "servo", "sensor", "conveyor", "error"]


# ── HTTP ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify({
        "conveyors":         list(get_conveyors().values()),
        "servos":            list(get_servos().values()),
        "servo_definitions": SERVO_DEFINITIONS,
        "counts":            get_counts(),
        "unrecognized":      get_unrecognized(),
        "session_start":     get_session_start(),
        "recent_events":     get_recent_events(limit=50, categories=LOGGED_CATEGORIES),
    })

# ── WebSocket latency test ─────────────────────────────────────────────────

@socketio.on("test_latency")
def test_latency(data):
    socketio.emit("latency_reply", data)


# ── Conveyor control  (frontend → server → broadcast → Pi) ───────────────────

@socketio.on("control_conveyor")
def handle_conveyor_control(data):
    conv_id = data.get("id")
    running = data.get("command") == "start"
    conveyors = get_conveyors()
    speed = conveyors[conv_id]["speed"] if running else 0.0
    save_conveyor(conv_id, running, speed)
    log_event("conveyor",
              f"Conveyor {conv_id} {'started' if running else 'stopped'}",
              f"speed={speed}")
    socketio.emit("update_conveyor", {
        "id":      conv_id,
        "running": running,
        "speed":   speed,
    })


# ── Conveyor state relay  (Pi ACK → server → browser) ────────────────────────

@socketio.on("conveyor_state")
def handle_conveyor_state(data):
    conv_id = data.get("id", "conveyor_1")
    running = bool(data.get("running", False))
    conveyors = get_conveyors()
    speed = conveyors.get(conv_id, {}).get("speed", 0.0) if running else 0.0
    save_conveyor(conv_id, running, speed)
    socketio.emit("update_conveyor", {
        "id":      conv_id,
        "running": running,
        "speed":   speed,
    })


# ── Servo activation  (Pi → server → browser) ────────────────────────────────
# Only handles active=True (label committed by YOLO).
# Deactivation is handled exclusively by servo_closed (Arduino feedback).

@socketio.on("servo_update")
def handle_servo_update(data):
    servo_type = data.get("type")
    active     = bool(data.get("active", False))

    if servo_type not in SERVO_DEFINITIONS:
        return

    save_servo(servo_type, active)
    servo_info = SERVO_DEFINITIONS[servo_type]

    if active:
        log_event("servo",
                  f"Servo {servo_info['index']} ({servo_type}) activated",
                  "waiting for Arduino confirmation")

    socketio.emit("update_servo", {
        "type":   servo_type,
        "active": active,
        "index":  servo_info["index"],
        "label":  servo_info["label"],
    })


# ── Servo deactivation  (Arduino CLOSED_OK / CLOSED_TIMEOUT → Pi → server → browser) ──
# This is the ONLY path that deactivates a servo — no timers.

@socketio.on("servo_closed")
def handle_servo_closed(data):
    servo_type  = data.get("type")
    close_status = data.get("status", "closed_ok")   # "closed_ok" or "closed_timeout"
    servo_idx   = data.get("index")

    if servo_type not in SERVO_DEFINITIONS:
        return

    save_servo(servo_type, False)
    servo_info = SERVO_DEFINITIONS[servo_type]

    log_event("servo",
              f"Servo {servo_info['index']} ({servo_type}) closed",
              close_status)

    socketio.emit("update_servo", {
        "type":         servo_type,
        "active":       False,
        "index":        servo_info["index"],
        "label":        servo_info["label"],
        "close_status": close_status,
    })


# ── Servo object detected  (informational relay) ──────────────────────────────

@socketio.on("servo_object_detected")
def handle_servo_object_detected(data):
    servo_type = data.get("type")
    servo_idx  = data.get("index")
    servo_info = SERVO_DEFINITIONS.get(servo_type, {})
    log_event("servo",
              f"Servo {servo_info.get('index', servo_idx)} ({servo_type}) object detected",
              None)
    socketio.emit("servo_object_detected", data)


# ── Servo error  (BLOCKED, etc.) ──────────────────────────────────────────────

@socketio.on("servo_error")
def handle_servo_error(data):
    servo_type = data.get("type")
    error      = data.get("error", "unknown")
    servo_idx  = data.get("index")
    servo_info = SERVO_DEFINITIONS.get(servo_type, {})

    log_event("error",
              f"Servo {servo_info.get('index', servo_idx)} ({servo_type}) error: {error}",
              None)
    socketio.emit("system_error", {
        "source": "servo",
        "servo":  servo_type,
        "index":  servo_idx,
        "error":  error,
    })


# ── Arduino ERR lines → dashboard ─────────────────────────────────────────────

@socketio.on("arduino_error")
def handle_arduino_error(data):
    error = data.get("error", "unknown")
    raw   = data.get("raw", "")
    log_event("error", f"Arduino error: {error}", raw or None)
    socketio.emit("system_error", {
        "source": "arduino",
        "error":  error,
        "raw":    raw,
    })


# ── Arduino INFO lines (informational relay) ───────────────────────────────────

@socketio.on("arduino_info")
def handle_arduino_info(data):
    info = data.get("info", "")
    socketio.emit("system_info", {"info": info})


# ── Label ACK relay ────────────────────────────────────────────────────────────

@socketio.on("ack_label")
def handle_ack_label(data):
    socketio.emit("ack_label", data)


# ── STATUS snapshot relay  (Pi parsed STATUS: line → browser) ─────────────────

@socketio.on("status_snapshot")
def handle_status_snapshot(data):
    socketio.emit("status_snapshot", data)


# ── CHANGE event relay  (logging only) ────────────────────────────────────────

@socketio.on("change_event")
def handle_change_event(data):
    socketio.emit("change_event", data)


# ── Proximity sensor telemetry  (Pi → server → browser) ──────────────────────

@socketio.on("sensor_update")
def handle_sensor_update(data):
    sensor_id   = data.get("id")
    triggered   = bool(data.get("triggered", False))
    distance_cm = data.get("distance_cm")
    log_event("sensor",
              f"Sensor {sensor_id} {'TRIGGERED' if triggered else 'clear'}",
              f"distance={distance_cm}cm" if distance_cm is not None else None)
    socketio.emit("update_sensor", {
        "id":          sensor_id,
        "triggered":   triggered,
        "distance_cm": distance_cm,
    })


# ── Buffer debug state  (Pi → server → browser, relay only) ──────────────────

@socketio.on("buffer_update")
def handle_buffer_update(data):
    socketio.emit("buffer_update", data)


# ── YOLO detection  (Pi → server → browser) ──────────────────────────────────

@socketio.on("yolo_detection")
def handle_yolo_detection(data):
    label        = data.get("label", "unrecognized")
    confidence   = float(data.get("confidence", 0.0))
    display      = data.get("display", label.capitalize())
    breakdown    = data.get("breakdown", {})
    total_frames = data.get("total_frames", 0)
    timestamp    = datetime.datetime.now().isoformat(timespec="seconds")

    if label in KNOWN_CATEGORIES:
        increment_count(label)
        log_event("detection",
                  f"Detected '{label.capitalize()}'",
                  f"category={label} confidence={confidence:.0%} frames={total_frames}")
    else:
        label     = "unrecognized"
        new_total = increment_unrecognized()
        socketio.emit("unrecognized_alert", {
            "display":   display,
            "timestamp": timestamp,
            "total":     new_total,
        })

    socketio.emit("new_detection", {
        "label":        display,
        "category":     label,
        "confidence":   confidence,
        "breakdown":    breakdown,
        "total_frames": total_frames,
        "timestamp":    timestamp,
    })

    socketio.emit("update_counts", {
        "counts":       get_counts(),
        "unrecognized": get_unrecognized(),
    })


# ── Connection lifecycle ──────────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    conveyors = get_conveyors()
    servos    = get_servos()

    socketio.emit("servo_definitions", SERVO_DEFINITIONS)

    for conv_id, conv in conveyors.items():
        socketio.emit("update_conveyor", {
            "id":      conv_id,
            "running": conv.get("running", False),
            "speed":   conv.get("speed", 0.0),
        })

    for servo_type, servo_data in servos.items():
        if servo_type in SERVO_DEFINITIONS:
            info = SERVO_DEFINITIONS[servo_type]
            socketio.emit("update_servo", {
                "type":   servo_type,
                "active": servo_data.get("active", False),
                "index":  info["index"],
                "label":  info["label"],
            })

    for sensor_id in ["sensor_1", "sensor_2"]:
        socketio.emit("update_sensor", {
            "id":          sensor_id,
            "triggered":   False,
            "distance_cm": None,
        })


@socketio.on("disconnect")
def on_disconnect(*args):
    pass


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)