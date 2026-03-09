import time
import random
import threading
from datetime import datetime
from flask import render_template

from app import app, socketio

from Database import (
    get_conveyors,
    get_servos,
    get_counts,
    get_unrecognized,
    get_session_start,
    save_conveyor,
    save_servo,
    increment_count,
    increment_unrecognized,
    log_event
)

# ─────────────────────────────────────────
# Object Types
# Must match frontend exactly
# ─────────────────────────────────────────

object_types = [
    "applicator",
    "ihmulator",
    "sharps",
    "hazardous"
]


# ─────────────────────────────────────────
# Live Stream Route 
# ─────────────────────────────────────────

@app.route("/live-stream")
def live_stream():
    return render_template("index.html")


# ─────────────────────────────────────────
# Rate Calculation
# ─────────────────────────────────────────

def compute_rate(total, session_start_iso):
    try:
        start = datetime.fromisoformat(session_start_iso)
        elapsed_h = (
            datetime.now() - start
        ).total_seconds() / 3600
        return round(total / elapsed_h) if elapsed_h > 0 else 0
    except:
        return 0


# ─────────────────────────────────────────
# Simulation Engine
# ─────────────────────────────────────────

def simulate_data():
    session_start = get_session_start()
    while True:
        conveyors = get_conveyors()
        servos = get_servos()
        # ───────── Object Detection ─────────
        if random.random() < 0.65:
            # Unrecognized object
            if random.random() < 0.08:
                total_unrec = increment_unrecognized()
                counts = get_counts()
                total = sum(counts.values())
                socketio.emit(
                    "unrecognized_object",
                    {
                        "total": total_unrec,
                        "message":
                        "Unrecognized object detected — verification required"
                    }
                )
                counts["rate"] = compute_rate(
                    total,
                    session_start
                )
                counts["unrecognized_rate"] = compute_rate(
                    total_unrec,
                    session_start
                )
                socketio.emit(
                    "update_counts",
                    counts
                )
            # Recognized object
            else:
                detected = random.choices(
                    object_types,
                    weights=[35, 28, 20, 17],
                    k=1
                )[0]
                increment_count(detected)
                counts = get_counts()
                total = sum(counts.values())
                unrecognized = get_unrecognized()
                counts["rate"] = compute_rate(
                    total,
                    session_start
                )
                counts["unrecognized_rate"] = compute_rate(
                    unrecognized,
                    session_start
                )
                socketio.emit(
                    "update_counts",
                    counts
                )
        # ───────── Conveyor Changes ─────────

        if random.random() < 0.08:
            conv_id = random.choice([1, 2])
            running = not conveyors[conv_id]["running"]
            new_speed = (
                round(random.uniform(0.8, 2.5), 1)
                if running
                else 0.0
            )
            save_conveyor(
                conv_id,
                running,
                new_speed
            )
            socketio.emit(
                "update_conveyor",
                {
                    "id": conv_id,
                    "running": running,
                    "speed": new_speed
                }
            )
        # ───────── Speed Variation ─────────
        if random.random() < 0.10:
            conv_id = random.choice([1, 2])
            if conveyors[conv_id]["running"]:
                new_speed = round(
                    random.uniform(0.8, 2.5),
                    1
                )
                save_conveyor(
                    conv_id,
                    True,
                    new_speed
                )
                socketio.emit(
                    "update_conveyor",
                    {
                        "id": conv_id,
                        "running": True,
                        "speed": new_speed
                    }
                )

        # ───────── Servo Activation ─────────
        if random.random() < 0.12:
            servo_type = random.choice(
                object_types
            )
            new_active = not servos[servo_type]["active"]
            save_servo(
                servo_type,
                new_active
            )
            socketio.emit(
                "update_servo",
                {
                    "type": servo_type,
                    "active": new_active
                }
            )
        # ───────── Alerts ─────────

        if random.random() < 0.03:
            messages = [
                "Metal detected in unsorted zone — jam risk",
                "Conveyor 1 speed abnormally low",
                "Applicator sensor blocked",
                "Hazardous objects detected in unsecured area",
                "Sharps servo maintenance recommended"
            ]
            msg = random.choice(
                messages
            )
            log_event(
                "alert",
                msg
            )
            socketio.emit(
                "new_alert",
                {
                    "message": msg
                }
            )
        time.sleep(
            random.uniform(
                1.1,
                2.8
            )
        )

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

if __name__ == "__main__":
    print("Simulation started")
    print("Database active")
    threading.Thread(
        target=simulate_data,
        daemon=True
    ).start()
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True,
        allow_unsafe_werkzeug=True
    )