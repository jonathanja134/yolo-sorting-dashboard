from flask import Flask
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app)

@socketio.on("control_conveyor")
def handle(data):
    socketio.emit("update_conveyor", data)

def test_socketio_event():
    client = socketio.test_client(app)
    client.emit("control_conveyor", {"id": "conveyor_1", "command": "start"})
    received = client.get_received()

    assert any(r["name"] == "update_conveyor" for r in received)
    assert any(r["name"] == "update_conveyor" and r["args"] == [{"id": "conveyor_1", "command": "start"}] for r in received)
