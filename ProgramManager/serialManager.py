import serial
import serial.tools.list_ports
import time

def _handle_status_line(line: str, emit_fn):
    """
    Parse STATUS:MOTOR:FORWARD|SENSOR1:CLEAR|... and emit a snapshot
    so the dashboard can sync state after any Arduino change.
    """
    content = line[7:]  # strip "STATUS:"
    snapshot = {}
    for token in content.split("|"):
        kv = token.split(":", 1)
        if len(kv) == 2:
            snapshot[kv[0]] = kv[1]
    emit_fn("status_snapshot", snapshot)

def serial_reader(serial_manager, emit_fn, buffer_manager, motor_state_setter, servo_index_to_category, set_active_servo):

    while True:
        if not serial_manager.serial_ok():
            time.sleep(0.1)
            continue
        try:
            line = serial_manager.read_line()
            if not line:
                continue
            print(f"[SERIAL <-] {line}")
            # separator lines
            if line.startswith("---"):
                continue
            # status snapshot
            if line.startswith("STATUS:"):
                _handle_status_line(line, emit_fn)
                continue
            # change annotation (log only)
            if line.startswith("CHANGE:"):
                emit_fn("change_event", {"change": line[7:]})
                continue
            parts = line.split(":")
            # sensor events
            if len(parts) == 3 and parts[0] == "SENSOR":
                sensor_id = parts[1]
                event = parts[2]
                # reset: commit previous, start fresh
                if sensor_id == "RESET" and event == "TRIGGERED":
                    buffer_manager.handle_reset()
                    continue
                # position sensors 1 and 2: dashboard only
                emit_fn(
                    "sensor_update",
                    {
                        "id": f"sensor_{sensor_id}",
                        "triggered": event == "TRIGGERED",
                        "distance_cm": None,
                    },
                )
                continue
            # motor ack -> update conveyor state on dashboard
            if len(parts) == 3 and parts[0] == "ACK" and parts[1] == "MOTOR":
                running = parts[2] == "FORWARD"
                motor_state_setter(running)
                print(f"[ARDUINO -> YOLO] Motor state = {'RUNNING' if running else 'STOP'}")
                emit_fn(
                    "conveyor_state",
                    {
                        "id": "conveyor_1",
                        "running": running,
                    },
                )
                continue
            # label ack
            if len(parts) == 3 and parts[0] == "ACK" and parts[1] == "LABEL":
                category = parts[2].lower()
                emit_fn("ack_label", {"category": category})
                continue
            # servo events
            if len(parts) >= 3 and parts[0] == "SERVO":
                try:
                    servo_idx = int(parts[1])
                    event = parts[2]
                except (ValueError, IndexError):
                    emit_fn(
                        "arduino_error",
                        {
                            "error": f"SERVO parse error: {line}",
                            "raw": line,
                        },
                    )
                    continue
                category = servo_index_to_category.get(servo_idx)
                if category is None:
                    emit_fn(
                        "arduino_error",
                        {
                            "error": f"Unknown servo index {servo_idx}",
                            "raw": line,
                        },
                    )
                    continue
                if event == "OPEN":
                    # Arduino confirmed open - dashboard already notified by
                    # servo_update(active=True) sent from commit_buffer.
                    pass
                elif event == "OBJECT_DETECTED":
                    emit_fn(
                        "servo_object_detected",
                        {
                            "type": category,
                            "index": servo_idx,
                        },
                    )
                elif event in ("CLOSED_OK", "CLOSED_TIMEOUT"):
                    # Primary servo deactivation path - driven by Arduino feedback.
                    set_active_servo(None, 0.0)
                    emit_fn(
                        "servo_closed",
                        {
                            "type": category,
                            "index": servo_idx,
                            "status": event.lower(),
                        },
                    )
                elif event == "BLOCKED":
                    emit_fn(
                        "servo_error",
                        {
                            "type": category,
                            "index": servo_idx,
                            "error": "blocked_at_start",
                        },
                    )
                continue
            # error messages -> relay to dashboard
            if parts[0] == "ERR":
                detail = ":".join(parts[1:])
                emit_fn(
                    "arduino_error",
                    {
                        "error": detail,
                        "raw": line,
                    },
                )
                continue
            if parts[0] == "INFO":
                detail = ":".join(parts[1:])
                emit_fn(
                    "arduino_info",
                    {
                        "info": detail,
                        "raw": line,
                    },
                )
                continue
            # boot/ready banner - ignore
            if "Sorting System Ready" in line:
                continue
            # anything unrecognized
            emit_fn(
                "arduino_error",
                {
                    "error": f"Unrecognised serial line: {line}",
                    "raw": line,
                },
            )
        except Exception as e:
            print(f"[SERIAL] read error: {e}")
            time.sleep(0.05)

class SerialManager:
    def __init__(self, baud=9600):
        self.baud = baud
        self.ser = None
        self.port = None
        self.available = False
        
    # ── PORT DETECTION ─────────────────────────────d
    def find_arduino_port(self):
        ports = serial.tools.list_ports.comports()
        candidates = []
    
        for p in ports:
            d = p.device
            # Linux
            if "/dev/ttyACM" in d or "/dev/ttyUSB" in d:
                candidates.append(d)
            # macOS
            elif "usbmodem" in d or "usbserial" in d or "/dev/tty." in d:
                candidates.append(d)
            # Windows
            elif d.startswith("COM"):
                candidates.append(d)
    
        for port in candidates:
            try:
                ser = serial.Serial(port, self.baud, timeout=0.05)
                time.sleep(2)
                ser.write(b"\n")
                ser.close()
                print(f"[SERIAL] Arduino found on {port}")
                return port
            except Exception:
                continue
        return None

    # ── CONNECT ────────────────────────────────────
    def connect(self):
        self.port = self.find_arduino_port()
        if self.port is None:
            self.available = False
            print("[SERIAL WARNING] No Arduino detected — running in OFFLINE mode")
            return
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
            time.sleep(2)
            self.available = True
            print(f"[SERIAL] Connected on {self.port}")
        except Exception as e:
            self.ser = None
            self.available = False
            print(f"[SERIAL WARNING] Failed to connect: {e} — OFFLINE mode")

    # ── CHECK ───────────────────────────────────────
    def serial_ok(self):
        return self.ser is not None and getattr(self.ser, "is_open", False)

    # ── SEND ───────────────────────────────────────
    def send(self, msg: str):
        if not self.serial_ok():
            return   # silently ignore in offline mode
        try:
            self.ser.write((msg + "\n").encode())
            print(f"[SERIAL →] {msg}")
        except Exception as e:
            print(f"[SERIAL ERROR] {e}")
            self.ser = None
            self.available = False

    def read_line(self):
        if not self.serial_ok():
            return None
        try:
            return self.ser.readline().decode(errors="ignore").strip()
        except:
            self.ser = None
            return None
        
    def close(self):
        try:
            if self.ser:
                self.ser.close()
                print("[SERIAL] Closed connection")
        except Exception as e:
            print(f"[SERIAL] Close error: {e}")
        finally:
            self.ser = None     