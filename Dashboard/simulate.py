import json
import time
import random
import threading
from app import app, socketio
from flask import render_template

# ─── Types d'objets ───────────────────────────────────────────────────────────
object_types = ["applicator", "ihmulator", "sharps", "hazardous"]

# Compteurs cumulés
counts = {t: 0 for t in object_types}
unrecognized_count = 0

# État des convoyeurs (avec vitesse en m/s)
conveyors = {
    1: {"id": 1, "running": True, "speed": 1.4},
    2: {"id": 2, "running": True, "speed": 1.2},
}

# État des servos
servos = {t: {"type": t, "active": False} for t in object_types}

# Horodatage de la session pour le calcul du taux horaire
session_start = time.time()


def simulate_data():
    global unrecognized_count

    while True:
        # ─── Détection d'un objet 
        if random.random() < 0.65:
            # 8% de chance qu'un objet ne soit pas reconnu
            if random.random() < 0.08:
                unrecognized_count += 1
                socketio.emit("unrecognized_object", {
                    "total": unrecognized_count,
                    "message": "Unknow object, required verification"
                })
            else:
                detected = random.choices(
                    object_types,
                    weights=[35, 28, 20, 17],
                    k=1
                )[0]
                counts[detected] += 1

                # Calcul du taux horaire
                elapsed_h = (time.time() - session_start) / 3600
                total = sum(counts.values())
                rate = round(total / elapsed_h) if elapsed_h > 0 else 0
                unrecognized_rate = round(unrecognized_count / elapsed_h) if elapsed_h > 0 else 0

                socketio.emit("update_counts", {
                    **counts,
                    "rate": rate,
                    "unrecognized_rate": unrecognized_rate
                })

        # ─── Changement d'état convoyeur ───────────────────────────────────
        if random.random() < 0.08:
            conv_id = random.choice([1, 2])
            conveyors[conv_id]["running"] = not conveyors[conv_id]["running"]
            if conveyors[conv_id]["running"]:
                conveyors[conv_id]["speed"] = round(random.uniform(0.8, 2.5), 1)
            else:
                conveyors[conv_id]["speed"] = 0.0
            socketio.emit("update_conveyor", conveyors[conv_id])

        # ─── Variation de vitesse sans arrêt ───────────────────────────────
        if random.random() < 0.10:
            conv_id = random.choice([1, 2])
            if conveyors[conv_id]["running"]:
                conveyors[conv_id]["speed"] = round(random.uniform(0.8, 2.5), 1)
                socketio.emit("update_conveyor", conveyors[conv_id])

        # ─── Activation aléatoire des servos ──────────────────────────────
        if random.random() < 0.12:
            servo_type = random.choice(object_types)
            servos[servo_type]["active"] = not servos[servo_type]["active"]
            socketio.emit("update_servo", servos[servo_type])

        # ─── Alerte occasionnelle ──────────────────────────────────────────
        if random.random() < 0.03:
            messages = [
                "Anomalie: Conveyor speed to slow ",
                "Stock object",
            ]
            socketio.emit("new_alert", {"message": random.choice(messages)})

        time.sleep(random.uniform(1.1, 2.8))


if __name__ == "__main__":
    print("Simulation démarrée…")
    threading.Thread(target=simulate_data, daemon=True).start()
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True,
        allow_unsafe_werkzeug=True
    )

# Add route for live video stream
def setup_routes():
    @app.route("/live-stream")
    def live_stream():
        return render_template("index.html")

setup_routes()