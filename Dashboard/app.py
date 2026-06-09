"""
app.py  –  Flask + SocketIO backend for the Sorting Control Dashboard.

Canonical servo / category mapping:
  canister   → Servo 1 – pin 12
  chemical   → Servo 2 – pin 13
  applicator → Servo 3 – pin 14
  inhaler    → Servo 4 – pin 15
    

SocketIO events
───────────────
FROM frontend  →  control_conveyor
FROM Pi        →  servo_update        (active=True when label committed)
                  servo_closed        (active=False, driven by Arduino CLOSED_OK/TIMEOUT)
                  servo_object_detected
                  sensor_update
                  yolo_detection
                  buffer_update
                  conveyor_state
                  ack_label           (ACK:LABEL:* from Arduino)
                  status_snapshot     (parsed STATUS: line)
                  change_event        (CHANGE: line)
TO   frontend  →  update_conveyor | update_servo | update_sensor
                  update_counts   | new_detection
                  buffer_update   (relayed straight to browser)
                  servo_definitions (on connect)
                  system_error    (ErrorManager WARNING+ → banner + log)
                  system_log      (ErrorManager INFO → log only)
                  error_resolved
                  status_snapshot (relayed to browser)
"""
import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from ProgramManager.config import normalize_conveyor_db_id
from Dashboard.Database import ( 
    init_db,get_conveyors, save_conveyor,get_servos,
    save_servo, reset_all_servos,get_counts,increment_count,
    get_unrecognized, increment_unrecognized,get_recent_events,
    get_session_start,record_sensor1_trigger, compute_sorting_rate,log_event)
from ProgramManager.ErrorManager import get_error_manager
from ProgramManager.config import SOCKET_PORT
from ProgramManager.serialManager import SerialManager

serial_manager = SerialManager()
app      = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

def _arduino_status():
    return {
        "connected": serial_manager.available,
        "port": serial_manager.port or "unknown",
    }

def _dashboard_emit(event, data):
    """Emit to browsers; mark server-origin so relay handler does not re-broadcast."""
    payload = dict(data)
    if event in ("system_error", "system_log", "error_resolved"):
        payload["_from_server"] = True
    if event == "system_error" and payload.get("severity") != "info":
        key = payload.get("error_key") or payload.get("code")
        _active_banner_errors[key] = payload
    socketio.emit(event, payload)


def _err_mgr():
    return get_error_manager(_dashboard_emit)


init_db()

# ── Canonical servo definitions ───────────────────────────────────────────────
SERVO_DEFINITIONS = {
    "canister":   {"label": "Servo 1 – Canister",   "index": 1},
    "chemical":   {"label": "Servo 2 – Chemical",   "index": 2},
    "applicator": {"label": "Servo 3 – Applicator", "index": 3},
    "inhaler":    {"label": "Servo 4 – Inhaler",    "index": 4},
}

KNOWN_CATEGORIES = set(SERVO_DEFINITIONS.keys())

# Categories stored in the event log — used by the filter UI
LOGGED_CATEGORIES = ["detection", "servo", "sensor", "conveyor", "error"]

# ── Connection State Tracking ──────────────────────────────────────────────────
# Lamp states for status bar (red, orange, green, blue)
lamp_state = {
    "red": False,
    "orange": False,
    "green": False,
    "blue": False,
}
# Last relayed banner errors (for browser refresh sync)
_active_banner_errors = {}

NOMINAL_WARNING = ("System OK")
DISCONNECT_WARNING = "⚠ Arduino disconnected — conveyors are disabled."


def is_arduino_connected():
    """Check if Arduino is currently connected."""
    return serial_manager.available


def _current_warning():
    """Banner text for HTTP initial load (matches live socket behaviour)."""
    if not serial_manager.available:
        raise _err_mgr().raise_error("SERIAL_NOT_CONNECTED")
    else:
        return {"message": NOMINAL_WARNING, "is_error": False}

def _emit_counts():
    socketio.emit("update_counts", {
        "counts":       get_counts(),
        "unrecognized": get_unrecognized(),
        "rate":         compute_sorting_rate(),
    })


@socketio.on("lamp_update")
def handle_lamp_update(data):
    """Receive lamp updates from Pi and broadcast to browsers."""
    global lamp_state
    try:
        # Accept partial updates or full dict
        for k, v in dict(data).items():
            if k in lamp_state:
                lamp_state[k] = bool(v)
    except Exception:
        pass
    print(f"[DASHBOARD] lamp_update -> {lamp_state}")
    socketio.emit("lamp_update", lamp_state)


def _clear_servo_display():
    """Reset servo UI/DB when Arduino is offline (no phantom activations)."""
    reset_all_servos()
    for servo_type, info in SERVO_DEFINITIONS.items():
        socketio.emit("update_servo", {
            "type":   servo_type,
            "active": False,
            "index":  info["index"],
            "label":  info["label"],
        })


# ── HTTP ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# Digital twin (testing) — remove this route and templates/digital_twin.html to drop.
@app.route("/digital-twin")
def digital_twin():
    return render_template("digital_twin.html")


@app.route("/api/state")
def api_state():
    return jsonify({
        "conveyors":            list(get_conveyors().values()),
        "servos":               list(get_servos().values()),
        "servo_definitions":    SERVO_DEFINITIONS,
        "counts":               get_counts(),
        "unrecognized":         get_unrecognized(),
        "session_start":        get_session_start(),
        "recent_events":        get_recent_events(limit=50, categories=LOGGED_CATEGORIES),
        "arduino_status":       _arduino_status(),
        "lamps":                lamp_state,
        "warning":              _current_warning(),
        "active_errors":        list(_active_banner_errors.values()),
        "rate":                 compute_sorting_rate(),
    })

# ── WebSocket latency test ─────────────────────────────────────────────────

@socketio.on("test_latency")
def test_latency(data):
    socketio.emit("latency_reply", data)


# ── Conveyor control  (frontend → server → broadcast → Pi) ───────────────────

@socketio.on("control_conveyor")
def handle_conveyor_control(data):
    conv_id = normalize_conveyor_db_id(data.get("id"))
    running = data.get("command") == "start"

    if not is_arduino_connected():
        _err_mgr().raise_error("CONTROL_CONVEYOR_BLOCKED", {"conveyor_id": conv_id,})
        return

    conveyors = get_conveyors()
    log_event("conveyor",f"Conveyor system {'started' if running else 'stopped'}",f"triggered_by={conv_id}")
    # One physical motor — keep dashboard conveyors 1 & 2 aligned in DB and UI
    for cid in (1, 2):
        save_conveyor(cid, running)
        socketio.emit("update_conveyor", {
            "id":          cid,
            "running":     running,
            "force_motor": cid == conv_id,
        })


# ── Conveyor state relay  (Pi ACK → server → browser) ────────────────────────

@socketio.on("conveyor_state")
def handle_conveyor_state(data):

    conv_id = normalize_conveyor_db_id(data.get("id", "conveyor_1"))
    running = bool(data.get("running", False))
    save_conveyor(conv_id, running)
    socketio.emit("update_conveyor", {
        "id":      conv_id,
        "running": running,
    })


# ── Servo activation  (Arduino SERVO:OPEN → Pi → server → browser) ───────────
# YOLO may emit servo_update with active=False or from_arduino=False — ignored for UI.
# Deactivation is handled exclusively by servo_closed (Arduino feedback).

@socketio.on("servo_update")
def handle_servo_update(data):
    servo_type    = data.get("type")
    active        = bool(data.get("active", False))
    from_arduino  = bool(data.get("from_arduino", False))

    if servo_type not in SERVO_DEFINITIONS:
        return
    if active and not from_arduino:
        return
    if active and not is_arduino_connected():
        return
    
    save_servo(servo_type, active)
    servo_info = SERVO_DEFINITIONS[servo_type]

    if active:
        log_event("servo",
                  f"Servo {servo_info['index']} ({servo_type}) activated",
                  "Arduino SERVO:OPEN")
    socketio.emit("update_servo", {
        "type":   servo_type,
        "active": active,
        "index":  servo_info["index"],
        "label":  servo_info["label"],
    })

# ── Servo deactivation  (Arduino CLOSED_OK / CLOSED_TIMEOUT → Pi → server → browser) ──
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


# ── Arduino connection status (Pi tracking) ────────────────────────────────────
# Shows when Arduino is connected / disconnected to disable/enable conveyor controls

@socketio.on("arduino_connection")
def handle_arduino_connection(data):
    timestamp = data.get("timestamp", datetime.datetime.now().isoformat())
    log_event("system",
              f"Arduino {'CONNECTED' if _arduino_status()['connected'] else 'DISCONNECTED'}",
              f"port={_arduino_status()['port']}")

    if not _arduino_status()["connected"]:
        _clear_servo_display()
    else:
        _err_mgr().resolve_error("CONTROL_CONVEYOR_BLOCKED")

    socketio.emit("arduino_status", {
        "connected": _arduino_status()["connected"],
        "port": _arduino_status()["port"],
        "timestamp": timestamp,
        "warning": _current_warning(),
        "conveyors": list(get_conveyors().values())
    })


# ── Label ACK relay ────────────────────────────────────────────────────────────

@socketio.on("ack_label")
def handle_ack_label(data):
    socketio.emit("ack_label", data)


# ── STATUS snapshot relay  (Pi parsed STATUS: line -> browser) ─────────────────

@socketio.on("status_snapshot")
def handle_status_snapshot(data):
    socketio.emit("status_snapshot", data)


# ── CHANGE event relay  (logging only) ────────────────────────────────────────

@socketio.on("change_event")
def handle_change_event(data):
    socketio.emit("change_event", data)


# ── Proximity sensor telemetry  (Pi -> server -> browser) ──────────────────────

@socketio.on("sensor_update")
def handle_sensor_update(data):
    sensor_id   = data.get("id")
    triggered   = bool(data.get("triggered", False))
    log_event("sensor",f"Sensor {sensor_id} {'TRIGGERED' if triggered else 'clear'}")
    if sensor_id == "sensor_1" and triggered:
        record_sensor1_trigger()
        _emit_counts()
    socketio.emit("update_sensor", {
        "id":          sensor_id,
        "triggered":   triggered,
    })


# ── Buffer debug state  (Pi -> server -> browser, relay only) ──────────────────

@socketio.on("buffer_update")
def handle_buffer_update(data):
    socketio.emit("buffer_update", data)


# ── YOLO detection  (Pi -> server -> browser) ──────────────────────────────────

@socketio.on("yolo_detection")
def handle_yolo_detection(data):
    raw_label    = data.get("label", "unrecognized")
    label        = str(raw_label).lower()
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
        label = "unrecognized"
        increment_unrecognized()
        log_event("detection",
                  f"Detected '{label}'",
                  f"confidence={confidence:.0%} frames={total_frames}")

    socketio.emit("new_detection", {
        "label":        display,
        "category":     label,
        "confidence":   confidence,
        "breakdown":    breakdown,
        "total_frames": total_frames,
        "timestamp":    timestamp,
    })

    _emit_counts()


# ── Connection lifecycle ──────────────────────────────────────────────────────

@socketio.on("system_error")
def handle_system_error_from_pi(data):
    """Relay Pi-originated errors only (skip server broadcasts)."""
    if data.get("_from_server"):
        return
    if data.get("severity") != "info":
        key = data.get("error_key") or data.get("code")
        _active_banner_errors[key] = data
    socketio.emit("system_error", data)


@socketio.on("system_log")
def handle_system_log_from_pi(data):
    """Relay Pi-originated INFO logs only."""
    if data.get("_from_server"):
        return
    socketio.emit("system_log", data)


@socketio.on("error_resolved")
def handle_error_resolved(data):
    """Relay error clear events; browser restores nominal/disconnect banner."""
    key = data.get("error_key") or data.get("code")
    _active_banner_errors.pop(key, None)
    socketio.emit("error_resolved", data)
    # After resolving an error, emit current arduino status/warning so clients
    # refresh the banner if no active errors remain.
    socketio.emit("arduino_status", {
        "connected": _arduino_status()["connected"],
        "port": _arduino_status()["port"],
        "timestamp": datetime.datetime.now().isoformat(),
        "warning": _current_warning(),
        "conveyors": list(get_conveyors().values()),
    })


@socketio.on("connect")
def on_connect():
    conveyors = get_conveyors()
    servos    = get_servos()

    socketio.emit("servo_definitions", SERVO_DEFINITIONS)

    socketio.emit("arduino_status", {
        "connected": _arduino_status()["connected"],
        "port":      _arduino_status()["port"],
        "warning":   _current_warning(),
    }, to=request.sid)

    # send current lamps state to newly connected client
    socketio.emit("lamp_update", lamp_state, to=request.sid)

    for conv_id, conv in conveyors.items():
        socketio.emit("update_conveyor", {
            "id":      conv_id,
            "running": conv.get("running", False)
        })

    show_servo_active = _arduino_status()["connected"]
    for servo_type, servo_data in servos.items():
        if servo_type in SERVO_DEFINITIONS:
            info = SERVO_DEFINITIONS[servo_type]
            active = show_servo_active and servo_data.get("active", False)
            socketio.emit("update_servo", {
                "type":   servo_type,
                "active": active,
                "index":  info["index"],
                "label":  info["label"],
            })

    for sensor_id in ["sensor_1", "sensor_2"]:
        socketio.emit("update_sensor", {
            "id":          sensor_id,
            "triggered":   False,
            "distance_cm": None,
        })

    _emit_counts()

    for err in _active_banner_errors.values():
        socketio.emit("system_error", err, to=request.sid)


@socketio.on("disconnect")
def on_disconnect(*args):
    pass


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=SOCKET_PORT, debug=False, use_reloader=False,allow_unsafe_werkzeug=True)