from flask import Flask, render_template
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)

@app.route("/")
def index():
    return render_template("index.html")

# Commande reçue depuis le frontend pour contrôler un convoyeur
@socketio.on("control_conveyor")
def handle_conveyor_control(data):
    print(f"Commande convoyeur reçue : {data}")
    # Plus tard : publier une commande MQTT vers la Raspberry ici


