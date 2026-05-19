import queue
import socketio
import threading
import time

from ProgramManager.ErrorManager import get_error_manager


class SocketManager:
    def __init__(
        self,
        server_url,
        get_motor_running_fn,      # Legacy: returns state for conveyor_1
        set_motor_running_fn,      # Legacy: sets state for conveyor_1
        serial_send_fn,
        get_multi_conveyor_fn=None,  # New: returns dict of all conveyor states
        set_multi_conveyor_fn=None,  # New: sets state for a specific conveyor
        emit_fn=None,                # New: for error reporting
    ):
        self.server_url = server_url
        self.get_motor_running_fn = get_motor_running_fn
        self.set_motor_running_fn = set_motor_running_fn
        self.serial_send_fn = serial_send_fn
        self.get_multi_conveyor_fn = get_multi_conveyor_fn
        self.set_multi_conveyor_fn = set_multi_conveyor_fn
        self.emit_fn = emit_fn

        self.sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self._emit_queue = queue.Queue()
        self._register_handlers()

    def _register_handlers(self):
        @self.sio.on("connect")
        def on_sio_connect():
            print("[SIO] connected - emitting initial conveyor states")
            get_error_manager(self.emit_fn).replay_pending()
            # Send all 3 conveyor states
            if self.get_multi_conveyor_fn:
                states = self.get_multi_conveyor_fn()
                for conv_id, state in states.items():
                    self.async_emit("conveyor_state", {
                        "id": conv_id,
                        "running": state,
                    })
            else:
                # Fallback to legacy single conveyor
                self.async_emit("conveyor_state", {
                    "id": "conveyor_1",
                    "running": self.get_motor_running_fn(),
                })

        @self.sio.on("latency_reply")
        def on_latency_reply(data):
            dt = time.time() - data["t"]
            print(f"Latency: {dt*1000:.1f} ms")

        @self.sio.on("update_conveyor")
        def on_conveyor_update(data):
            conv_id = data.get("id", "conveyor_1")
            requested = bool(data.get("running", False))

            # Use new multi-conveyor logic if available
            if self.set_multi_conveyor_fn:
                current_state = self.get_multi_conveyor_fn().get(conv_id, False)
                if requested == current_state:
                    return
                self.set_multi_conveyor_fn(conv_id, requested)
                cmd = f"MOTOR:{conv_id}:FORWARD" if requested else f"MOTOR:{conv_id}:STOP"
            else:
                # Fallback to legacy single conveyor (conveyor_1 only)
                if requested == self.get_motor_running_fn():
                    return
                self.set_motor_running_fn(requested)
                cmd = "MOTOR:FORWARD" if requested else "MOTOR:STOP"

            # Call serial_send with emit_fn if available (for error reporting)
            if self.emit_fn:
                self.serial_send_fn(cmd, emit_fn=self.emit_fn)
            else:
                self.serial_send_fn(cmd)
            print(f"[DASHBOARD -> YOLO] {conv_id}: {'RUNNING' if requested else 'STOP'}")

    def _emit_worker(self):
        while True:
            event, data = self._emit_queue.get()
            try:
                if self.sio.connected:
                    self.sio.emit(event, data)
            except Exception as e:
                print(f"[EMIT] error: {e}")
            finally:
                self._emit_queue.task_done()

    def async_emit(self, event, data):
        self._emit_queue.put_nowait((event, data))

    def connect_loop(self):
        while True:
            try:
                self.sio.connect(self.server_url)
                print(f"SocketIO connected to {self.server_url} ({self.sio.transport()})")
                self.sio.emit("test_latency", {"t": time.time()})
                break
            except Exception as e:
                print(f"SocketIO connect failed ({e}), retrying...")
                time.sleep(3)

    def wait_until_connected(self, timeout=20.0):
        """Block until connected to the dashboard (for startup error delivery)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.sio.connected:
                return True
            time.sleep(0.1)
        return False

    def start(self):
        threading.Thread(target=self._emit_worker, daemon=True).start()
        threading.Thread(target=self.connect_loop, daemon=True).start()
