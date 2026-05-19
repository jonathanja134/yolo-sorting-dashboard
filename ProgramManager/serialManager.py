import serial
import serial.tools.list_ports
import time
from ProgramManager.config import BAUD, PORT
from ProgramManager.ErrorManager import get_error_manager

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

def serial_reader(serial_manager, emit_fn, buffer_manager, motor_state_setter, servo_index_to_category, set_active_servo, multi_motor_state_setter=None):
    """
    Read from serial port and dispatch events.
    Tracks and emits Arduino connection status.
    """
    error_mgr = get_error_manager(emit_fn)
    last_connection_state = None
    
    while True:
        current_connected = serial_manager.serial_ok()
        
        # Emit connection state changes
        if current_connected != last_connection_state:
            last_connection_state = current_connected
            if current_connected:
                error_mgr.resolve_error("SERIAL_NOT_CONNECTED")
                print("[SERIAL] ✓ Arduino connected")
                emit_fn("arduino_connection", {
                    "connected": True,
                    "port": serial_manager.port,
                    "timestamp": time.time(),
                })
            else:
                error_mgr.raise_error("SERIAL_NOT_CONNECTED", {
                    "port": serial_manager.port,
                    "reason": "Connection lost or not established",
                })
                emit_fn("arduino_connection", {
                    "connected": False,
                    "port": serial_manager.port,
                    "timestamp": time.time(),
                })
        
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
            # Supports both old (ACK:MOTOR:FORWARD) and new (ACK:MOTOR1:FORWARD, etc.) formats
            if len(parts) >= 3 and parts[0] == "ACK" and parts[1].startswith("MOTOR"):
                motor_id = parts[1]  # "MOTOR", "MOTOR1", "MOTOR2", "MOTOR3"
                status = parts[2]    # "FORWARD" or "STOP"
                running = status == "FORWARD"
                
                # Map motor ID to conveyor ID
                if motor_id == "MOTOR":
                    # Legacy: ACK:MOTOR:FORWARD -> conveyor_1
                    conv_id = "conveyor_1"
                    motor_state_setter(running)
                else:
                    # New: ACK:MOTOR1:FORWARD -> conveyor_1, ACK:MOTOR2:FORWARD -> conveyor_2, etc.
                    try:
                        motor_num = int(motor_id[5:])  # Extract number from "MOTORx"
                        conv_id = f"conveyor_{motor_num}"
                        if multi_motor_state_setter:
                            multi_motor_state_setter(conv_id, running)
                        else:
                            # Fallback to legacy if multi not provided
                            if conv_id == "conveyor_1":
                                motor_state_setter(running)
                    except (ValueError, IndexError):
                        error_mgr.raise_error("SERIAL_PARSE_ERROR", {
                            "message": f"MOTOR parse error: {line}",
                            "message_type": "MOTOR",
                            "raw": line,
                        })
                        continue
                
                print(f"[ARDUINO -> YOLO] {conv_id} state = {'RUNNING' if running else 'STOP'}")
                emit_fn(
                    "conveyor_state",
                    {
                        "id": conv_id,
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
                    error_mgr.raise_error("SERIAL_PARSE_ERROR", {
                        "message": f"SERVO parse error: {line}",
                        "message_type": "SERVO",
                        "raw": line,
                    })
                    continue
                category = servo_index_to_category.get(servo_idx)
                if category is None:
                    error_mgr.raise_error("SERVO_INVALID_INDEX", {
                        "message": f"Unknown servo index {servo_idx}",
                        "servo_index": servo_idx,
                        "raw": line,
                    })
                    continue
                if event == "OPEN":
                    error_mgr.resolve_error("SERVO_BLOCKED")
                    emit_fn(
                        "servo_update",
                        {
                            "type": category,
                            "active": True,
                            "from_arduino": True,
                        },
                    )
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
                    if event == "CLOSED_TIMEOUT":
                        error_mgr.raise_error("SERVO_TIMEOUT", {
                            "message": (
                                f"Servo {servo_idx} ({category}) closed on timeout — "
                                "object may not have passed."
                            ),
                            "servo_type": category,
                            "servo_index": servo_idx,
                        })
                    else:
                        error_mgr.resolve_error("SERVO_TIMEOUT")
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
                    error_mgr.raise_error("SERVO_BLOCKED", {
                        "message": f"Servo {servo_idx} ({category}) blocked at start",
                        "servo_type": category,
                        "servo_index": servo_idx,
                    })
                continue
            # error messages -> relay to dashboard
            if parts[0] == "ERR":
                detail = ":".join(parts[1:])
                error_mgr.raise_error("ARDUINO_ERR", {
                    "message": detail,
                    "raw": line,
                })
                continue
            if parts[0] == "INFO":
                detail = ":".join(parts[1:])
                error_mgr.log_info("ARDUINO_INFO", {
                    "message": detail,
                    "raw": line,
                })
                continue
            # boot/ready banner - ignore
            if "Sorting System Ready" in line:
                continue
            # anything unrecognized
            error_mgr.raise_error("SERIAL_UNRECOGNIZED_LINE", {
                "message": f"Unrecognised serial line: {line}",
                "raw": line,
            })
        except Exception as e:
            print(f"[SERIAL] read error: {e}")
            error_mgr.raise_error("SERIAL_READ_ERROR", {
                "exception": str(e),
            })
            time.sleep(0.05)

class SerialManager:
    def __init__(self, baud=BAUD):
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
    def connect(self, port=None, emit_fn=None):
        """
        Connect to Arduino on specified or detected port.
        Args:
            port: Explicit port name or None to auto-detect
            emit_fn: Optional callback to emit connection errors
        """
        error_mgr = get_error_manager(emit_fn)
        
        if port:
            self.port = port
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
                time.sleep(2)
                self.available = True
                print(f"[SERIAL] Connected on explicit port {self.port}")
                return
            except Exception as e:
                self.ser = None
                self.available = False
                if error_mgr:
                    error_mgr.raise_error("SERIAL_CONNECT_FAILED", {
                        "port": self.port,
                        "reason": str(e),
                    })
                print(f"[SERIAL WARNING] Failed to connect on explicit port {self.port}: {e}")

        self.port = self.find_arduino_port()
        if self.port is None:
            self.available = False
            if error_mgr:
                error_mgr.raise_error("SERIAL_PORT_NOT_FOUND", {
                    "reason": "No Arduino detected on any available port",
                })
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
            if error_mgr:
                error_mgr.raise_error("SERIAL_CONNECT_FAILED", {
                    "port": self.port,
                    "reason": str(e),
                })
            print(f"[SERIAL WARNING] Failed to connect: {e} — OFFLINE mode")

    # ── CHECK ───────────────────────────────────────
    def serial_ok(self):
        return self.ser is not None and getattr(self.ser, "is_open", False)

    # ── SEND ───────────────────────────────────────
    def send(self, msg: str, emit_fn=None):
        """Send a message to Arduino."""
        error_mgr = get_error_manager(emit_fn)
        
        if not self.serial_ok():
            msg_short = msg[:50] + "..." if len(msg) > 50 else msg
            print(f"[SERIAL WARNING] write ignored because serial is not connected: {msg_short}")
            if error_mgr:
                error_mgr.raise_error("SERIAL_NOT_CONNECTED", {
                    "attempted_message": msg_short,
                })
            return
        try:
            self.ser.write((msg + "\n").encode())
            print(f"[SERIAL →] {msg}")
        except Exception as e:
            print(f"[SERIAL ERROR] {e}")
            if error_mgr:
                error_mgr.raise_error("SERIAL_WRITE_ERROR", {
                    "exception": str(e),
                    "message": msg,
                })
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