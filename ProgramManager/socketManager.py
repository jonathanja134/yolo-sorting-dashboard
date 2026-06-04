import queue
from cv2 import data
import socketio
import threading
import time

from ProgramManager.ErrorManager import get_error_manager
from ProgramManager.config import conveyor_socket_id, normalize_conveyor_db_id


# Dashboard shows conveyors 1–2; one physical motor drives both.
_MOTOR_CONVEYORS = ("conveyor_1", "conveyor_2")
_ALL_CONVEYORS = ("conveyor_1", "conveyor_2", "conveyor_3")


class SocketManager:
    def __init__(
        self,
        server_url,
        serial_send_fn,
        get_multi_conveyor_fn,
        set_multi_conveyor_fn,
        emit_fn=None,
        serial_ok_fn=None,
    ):
        self.server_url = server_url
        self.serial_send_fn = serial_send_fn
        self.get_multi_conveyor_fn = get_multi_conveyor_fn
        self.set_multi_conveyor_fn = set_multi_conveyor_fn
        self.emit_fn = emit_fn
        self.serial_ok_fn = serial_ok_fn
        self._motor_physically_running = False

        self.sio = socketio.Client(reconnection=True, reconnection_attempts=0)
        self._emit_queue = queue.Queue()
        self._register_handlers()

    def _register_handlers(self):
        @self.sio.on("connect")
        def on_sio_connect():
            print("[SIO] connected - emitting initial conveyor states")
            get_error_manager(self.emit_fn).replay_pending()
            if self.serial_ok_fn:
                connected = self.serial_ok_fn()
                self.async_emit("arduino_connection", {
                    "connected": connected,
                    "port": None,
                    "timestamp": time.time(),
                })
            states = self.get_multi_conveyor_fn()
            self._motor_physically_running = self._any_dashboard_conveyor_running(states)
            for conv_id, state in states.items():
                self.async_emit("conveyor_state", {
                    "id": conv_id,
                    "running": state,
                })

        @self.sio.on("latency_reply")
        def on_latency_reply(data):
            dt = time.time() - data["t"]
            print(f"Latency: {dt*1000:.1f} ms")

        @self.sio.on("update_conveyor")
        def on_conveyor_update(data):
            db_id = normalize_conveyor_db_id(data.get("id"), default=1)
            conv_id = conveyor_socket_id(db_id)
            requested = bool(data.get("running", False))
            force_motor = bool(data.get("force_motor", False))

            if force_motor:
                self._apply_dashboard_motor_command(requested)
                return

            # Arduino / status relay — update state only, never write serial
            self.set_multi_conveyor_fn(conv_id, requested)
            states = self.get_multi_conveyor_fn()
            self._motor_physically_running = self._any_dashboard_conveyor_running(states)

    @staticmethod
    def _any_dashboard_conveyor_running(states):
        return any(states.get(cid, False) for cid in _MOTOR_CONVEYORS)

    def _apply_dashboard_motor_command(self, running):
        """Dashboard button toggles the shared motor; keep all conveyors in sync."""
        for cid in _ALL_CONVEYORS:
            self.set_multi_conveyor_fn(cid, running)

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