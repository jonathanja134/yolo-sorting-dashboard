"""
app.py  –  Flask + SocketIO backend for the Sorting Control Dashboard.

4 servo categories
------------------
  canister    → Servo 1 – Canister
  sharps      → Servo 2 – Apply Pen / Syringes / Bag
  applicator  → Servo 3 – Applicator
  inhaler     → Servo 4 – Inhaler

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
import threading

app      = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

init_db()

# ── 4 servo definitions ───────────────────────────────────────────────────────
SERVO_DEFINITIONS = {
    "canister":   {"label": "Servo 1 – Canister",                   "index": 1},
    "sharps":     {"label": "Servo 2 – Apply Pen / Syringes / Bag", "index": 2},
    "applicator": {"label": "Servo 3 – Applicator",                 "index": 3},
    "inhaler":    {"label": "Servo 4 – Inhaler",                    "index": 4},
}

KNOWN_CATEGORIES = set(SERVO_DEFINITIONS.keys())

# Events worth keeping — connect/disconnect noise is excluded
LOGGED_CATEGORIES = ["detection", "servo", "sensor", "conveyor"]


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
        # Only return meaningful events — no connect/disconnect noise
        "recent_events":     get_recent_events(limit=50, categories=LOGGED_CATEGORIES),
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
    servo_type = data.get("type")
    active     = bool(data.get("active", False))

    if servo_type not in SERVO_DEFINITIONS:
        return

    save_servo(servo_type, active)

    servo_info = SERVO_DEFINITIONS[servo_type]
    socketio.emit("update_servo", {
        "type":   servo_type,
        "active": active,
        "index":  servo_info["index"],
        "label":  servo_info["label"],
    })

    # Deactivation delay depends on category:
    #   canister / sharps      → 3 s  (quick divert)
    #   applicator / inhaler   → 7 s  (longer divert arm travel)
    DEACTIVATION_DELAY = {
        "canister":   3.0,
        "sharps":     3.0,
        "applicator": 7.0,
        "inhaler":    7.0,
    }
    if active:
        delay = DEACTIVATION_DELAY.get(servo_type, 3.0)
        def _deactivate(st=servo_type, si=servo_info, d=delay):
            import time; time.sleep(d)
            save_servo(st, False)
            socketio.emit("update_servo", {
                "type":   st,
                "active": False,
                "index":  si["index"],
                "label":  si["label"],
            })
        threading.Thread(target=_deactivate, daemon=True).start()


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
    # Relay only — not logged to DB (too frequent)
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


# ── Connection lifecycle — no DB logging (was flooding the events table) ──────

@socketio.on("connect")
def on_connect():
    # Send servo definitions so the UI can build servo cards
    socketio.emit("servo_definitions", SERVO_DEFINITIONS)


@socketio.on("disconnect")
def on_disconnect(*args):
    pass


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)