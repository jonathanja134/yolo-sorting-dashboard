import queue
import socketio
import threading
import time


class SocketManager:
    def __init__(
        self,
        server_url,
        get_motor_running_fn,
        set_motor_running_fn,
        serial_send_fn,
    ):
        self.server_url = server_url
        self.get_motor_running_fn = get_motor_running_fn
        self.set_motor_running_fn = set_motor_running_fn
        self.serial_send_fn = serial_send_fn

        self.sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self._emit_queue = queue.Queue()
        self._register_handlers()

    def _register_handlers(self):
        @self.sio.on("connect")
        def on_sio_connect():
            print("[SIO] connected - emitting initial conveyor state")
            self.async_emit(
                "conveyor_state",
                {
                    "id": "conveyor_1",
                    "running": self.get_motor_running_fn(),
                },
            )

        @self.sio.on("latency_reply")
        def on_latency_reply(data):
            dt = time.time() - data["t"]
            print(f"Latency: {dt*1000:.1f} ms")

        @self.sio.on("update_conveyor")
        def on_conveyor_update(data):
            requested = bool(data.get("running", False))
            if requested == self.get_motor_running_fn():
                return

            self.set_motor_running_fn(requested)
            cmd = "MOTOR:FORWARD" if requested else "MOTOR:STOP"
            self.serial_send_fn(cmd)
            print(f"[DASHBOARD -> YOLO] Request: {'RUNNING' if requested else 'STOP'}")

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

    def start(self):
        threading.Thread(target=self._emit_worker, daemon=True).start()
        threading.Thread(target=self.connect_loop, daemon=True).start()
