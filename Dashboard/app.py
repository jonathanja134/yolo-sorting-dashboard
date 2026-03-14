"""
app.py  –  Flask + SocketIO backend for the Sorting Control Dashboard.

SocketIO events
---------------
  FROM frontend  →  control_conveyor
  FROM Pi        →  servo_update | sensor_update | yolo_detection | buffer_update
  TO   frontend  →  update_conveyor | update_servo | update_sensor
                    update_counts   | new_detection | unrecognized_alert
                    buffer_update   (relayed straight to browser)
"""

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
from Database import (
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


# ── HTTP ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify({
        "conveyors":     list(get_conveyors().values()),
        "servos":        list(get_servos().values()),
        "counts":        get_counts(),
        "unrecognized":  get_unrecognized(),
        "session_start": get_session_start(),
        "recent_events": get_recent_events(limit=20),
    })


# ── Conveyor control  (frontend → server → broadcast) ────────────────────────

@socketio.on("control_conveyor")
def handle_conveyor_control(data):
    conv_id = data.get("id")
    running = data.get("command") == "start"
    conveyors = get_conveyors()
    speed = conveyors[conv_id]["speed"] if running else 0.0
    save_conveyor(conv_id, running, speed)
    socketio.emit("update_conveyor", {
        "id":      conv_id,
        "running": running,
        "speed":   speed,
    })


# ── Servo telemetry  (Pi → server → browser) ─────────────────────────────────

@socketio.on("servo_update")
def handle_servo_update(data):
    """
    Payload: { "type": "applicator"|"inhaler"|"sharps"|"hazardous",
               "active": true|false }
    """
    servo_type = data.get("type")
    active     = bool(data.get("active", False))
    save_servo(servo_type, active)
    socketio.emit("update_servo", {"type": servo_type, "active": active})


# ── Proximity sensor telemetry  (Pi → server → browser) ──────────────────────

@socketio.on("sensor_update")
def handle_sensor_update(data):
    """
    Payload: { "id": "sensor_1"|"sensor_2",
               "triggered": bool, "distance_cm": float|None }
    """
    sensor_id   = data.get("id")
    triggered   = bool(data.get("triggered", False))
    distance_cm = data.get("distance_cm")
    log_event("sensor",
              f"Sensor {sensor_id} {'TRIGGERED' if triggered else 'clear'}",
              f"distance={distance_cm}cm")
    socketio.emit("update_sensor", {
        "id":          sensor_id,
        "triggered":   triggered,
        "distance_cm": distance_cm,
    })


# ── Buffer debug state  (Pi → server → browser, relay only) ──────────────────

@socketio.on("buffer_update")
def handle_buffer_update(data):
    """
    Live buffer percentages from the Pi's detection buffer.
    Relayed directly to all dashboard clients for the debug panel.

    Payload shape (from yolo_reader.py):
    {
        "collecting":   bool,
        "total_frames": int,
        "min_frames":   int,
        "gap_counter":  int,
        "gap_limit":    int,
        "breakdown":    { "applicator": {"count":7,"pct":70}, … },
        "leader":       "applicator" | null,
        "committed":    bool   (only on final commit frame)
        "winner":       str    (only on final commit frame)
        "confidence":   float  (only on final commit frame)
    }
    """
    socketio.emit("buffer_update", data)


# ── YOLO detection  (Pi → server → browser) ──────────────────────────────────

@socketio.on("yolo_detection")
def handle_yolo_detection(data):
    """
    Committed detection result after majority-vote buffer.

    Payload:
    {
        "label":        "applicator"|"inhaler"|"sharps"|"hazardous"|"unrecognized",
        "confidence":   0.94,
        "display":      "Inhaler blue",
        "breakdown":    { … },
        "total_frames": 12
    }
    """
    label       = data.get("label", "unrecognized")
    confidence  = float(data.get("confidence", 0.0))
    display     = data.get("display", label.capitalize())
    breakdown   = data.get("breakdown", {})
    total_frames= data.get("total_frames", 0)
    timestamp   = datetime.datetime.now().isoformat(timespec="seconds")

    KNOWN = {"applicator", "inhaler", "sharps", "hazardous"}

    if label in KNOWN:
        increment_count(label)
        log_event("detection",
                  f"Detected '{display}'",
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
    log_event("system", "Dashboard client connected")


@socketio.on("disconnect")
def on_disconnect(*args):
    # newer flask-socketio passes a reason argument — accept and ignore it
    log_event("system", "Dashboard client disconnected")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)