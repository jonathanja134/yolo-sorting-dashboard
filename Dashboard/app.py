from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
from Database import init_db, get_conveyors, get_servos, get_counts, get_unrecognized, save_conveyor, log_event

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize the database on startup
init_db()


@app.route("/")
def index():
    return render_template("index.html")


# API: full current state so the frontend can restore everything on page load
@app.route("/api/state")
def api_state():
    conveyors = get_conveyors()
    servos    = get_servos()
    counts    = get_counts()
    return jsonify({
        "conveyors":    list(conveyors.values()),
        "servos":       list(servos.values()),
        "counts":       counts,
        "unrecognized": get_unrecognized()
    })


# Conveyor command received from the frontend (manual toggle)
@socketio.on("control_conveyor")
def handle_conveyor_control(data):
    conv_id = data.get("id")
    command = data.get("command")
    running = command == "start"

    conveyors = get_conveyors()
    speed = conveyors[conv_id]["speed"] if running else 0.0

    save_conveyor(conv_id, running, speed)
    log_event("conveyor", f"Manual {'start' if running else 'stop'} — Conveyor {conv_id}")

    # Broadcast updated state to all connected clients
    socketio.emit("update_conveyor", {
        "id":      conv_id,
        "running": running,
        "speed":   speed
    })