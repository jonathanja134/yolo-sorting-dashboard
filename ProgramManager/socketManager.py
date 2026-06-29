import queue
import socketio
import threading
import time

from ProgramManager.ErrorManager import get_error_manager
from ProgramManager.config import CONVEYOR_ID


class SocketManager:
    def __init__(
        self,
        server_url,
        serial_send_fn,
        get_conveyor_fn,
        set_conveyor_fn,
        emit_fn=None,
        serial_ok_fn=None,
        get_lamp_fn=None,
    ):
        self.server_url = server_url
        self.serial_send_fn = serial_send_fn
        self.get_conveyor_fn = get_conveyor_fn
        self.set_conveyor_fn = set_conveyor_fn
        self.emit_fn = emit_fn
        self.serial_ok_fn = serial_ok_fn
        self.get_lamp_fn = get_lamp_fn
        self._motor_physically_running = False

        self.sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self._emit_queue = queue.Queue()
        self._register_handlers()

    def _register_handlers(self):
        @self.sio.on("connect")
        def on_sio_connect():
            print("[SIO] connected - emitting initial conveyor state")
            get_error_manager(self.emit_fn).replay_pending()
            if self.serial_ok_fn:
                connected = self.serial_ok_fn()
                self.async_emit("arduino_connection", {
                    "connected": connected,
                    "port": None,
                    "timestamp": time.time(),
                })
            running = self.get_conveyor_fn()
            self._motor_physically_running = running
            self.async_emit("conveyor_state", {
                "id": CONVEYOR_ID,
                "running": running,
            })
            if self.get_lamp_fn:
                self.async_emit("lamp_update", self.get_lamp_fn())

        @self.sio.on("latency_reply")
        def on_latency_reply(data):
            dt = time.time() - data["t"]
            print(f"Latency: {dt*1000:.1f} ms")

        @self.sio.on("update_conveyor")
        def on_conveyor_update(data):
            requested = bool(data.get("running", False))
            force_motor = bool(data.get("force_motor", False))

            if force_motor:
                self._apply_dashboard_motor_command(requested)
                return

            # Arduino / status relay update state only
            self.set_conveyor_fn(requested)
            self._motor_physically_running = requested

    def _apply_dashboard_motor_command(self, running):
        "Dashboard STOP motors"
        self.set_conveyor_fn(running)

        if running == self._motor_physically_running:
            return

        self._motor_physically_running = running
        cmd = "MOTOR:FORWARD" if running else "MOTOR:STOP"
        if self.emit_fn:
            self.serial_send_fn(cmd, emit_fn=self.emit_fn)
        else:
            self.serial_send_fn(cmd)
        print(f"[DASHBOARD -> YOLO] system motor {'RUNNING' if running else 'STOP'}")

    def _emit_worker(self):
        while True:
            event, data = self._emit_queue.get()
            try:
                while not self.sio.connected:
                    time.sleep(0.1)
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
                self.sio.wait()
            except Exception as e:
                print(f"SocketIO connect failed ({e}), retrying...")
                time.sleep(3)

    def wait_until_connected(self, timeout=20.0):
        "Block operation until connected to the dashboard for startup error "
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.sio.connected:
                return True
            time.sleep(0.1)
        return False

    def start(self):
        threading.Thread(target=self._emit_worker, daemon=True).start()
        threading.Thread(target=self.connect_loop, daemon=True).start()
