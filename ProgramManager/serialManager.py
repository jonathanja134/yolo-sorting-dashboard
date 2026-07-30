import serial
import serial.tools.list_ports
import time
import threading
from ProgramManager.config import BAUD, CONVEYOR_ID
from ProgramManager.ErrorManager import get_error_manager

# Shared lamp state (serial_reader updates; SocketManager re-syncs on reconnect)
_lamp_state = {"red":False, "green":False, "orange":False, "blue":False,}

def get_lamp_state() -> dict:
    return dict(_lamp_state)


def serial_reader(serial_manager, emit_fn, servo_index_to_category, set_active_servo, set_conveyor_state=None):
    """
    Read from serial port and dispatch events.
    Tracks and emits Arduino connection status.
    """
    error_mgr = get_error_manager(emit_fn)
    last_connection_state = None
    unwired_servos = {}  # servo_idx -> {category, detail}
    # Track simple lamp + motor state so we can emit lamp updates
    lamp_state = _lamp_state
    motor_running  = False
    estop_active   = False

    def _sync_servo_not_wired_error():
        if not unwired_servos:
            error_mgr.resolve_error("SERVO_NOT_WIRED")
            return
        parts = []
        for idx in sorted(unwired_servos):
            entry = unwired_servos[idx]
            parts.append(f"Servo {idx} ({entry['category']}): {entry['detail']}")
        error_mgr.raise_error("SERVO_NOT_WIRED", {
            "message": "Servo(s) not wired: " + "; ".join(parts),
            "servo_indices": sorted(unwired_servos.keys()),
            "unwired_servos": {k: dict(v) for k, v in unwired_servos.items()},
        })

    while True:
        current_connected = serial_manager.serial_ok()

        #  Emit connection state changes 
        if current_connected != last_connection_state:
            last_connection_state = current_connected
            if current_connected:
                error_mgr.resolve_error("SERIAL_NOT_CONNECTED")
                unwired_servos.clear()
                error_mgr.resolve_error("SERVO_NOT_WIRED")
                print("[SERIAL] ✓ Arduino connected")
                emit_fn("arduino_connection", {
                    "connected":  True,
                    "port":       serial_manager.port,
                    "timestamp":  time.time(),
                })
            else:
                error_mgr.raise_error("SERIAL_NOT_CONNECTED", {
                    "port":   serial_manager.port,
                    "reason": "Connection lost or not established",
                })
                emit_fn("arduino_connection", {
                    "connected": False,
                    "port":      serial_manager.port,
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
            # Receiving any valid line means the Arduino is talking — clear connection warning
            error_mgr.resolve_error("SERIAL_NOT_CONNECTED")
            error_mgr.resolve_error("SERIAL_DEVICE_UNREACHABLE")
            
            parts = line.split(":")

            if line == "ESTOP:ACTIVE":
                estop_active   = True
                motor_running  = False
                lamp_state_updates = {} 
                if not lamp_state.get('red'):
                    lamp_state_updates['red']   = True
                    lamp_state['red']           = True
                if lamp_state.get('green'):
                    lamp_state_updates['green'] = False
                    lamp_state['green']         = False
                if lamp_state.get('orange'):
                    lamp_state_updates['orange'] = False
                    lamp_state['orange']         = False
                if lamp_state.get('blue'):
                    lamp_state_updates['blue'] = False
                    lamp_state['blue']         = False
                if lamp_state_updates:
                    emit_fn('lamp_update', lamp_state)
                error_mgr.raise_error("ESTOP_ACTIVE")
                continue

            elif line == "ESTOP:CLEARED":
                estop_active = False
                lamp_state_updates = {}
                if lamp_state.get('red'):
                    lamp_state_updates['red'] = False
                    lamp_state['red']         = False
                orange_should = (not motor_running) and (not estop_active)
                if lamp_state.get('orange') != orange_should:
                    lamp_state_updates['orange'] = orange_should
                    lamp_state['orange']         = orange_should
                if lamp_state_updates:
                    emit_fn('lamp_update', lamp_state)
                error_mgr.resolve_error("ESTOP_ACTIVE")
                error_mgr.log_info("ESTOP_CLEARED")
                continue

            # sensor events
            if len(parts) == 3 and parts[0] == "SENSOR":
                sensor_id = parts[1]
                event     = parts[2]
                if sensor_id == "END" and event == "OBJECT_NOT_DETECTED":
                    emit_fn("unsorted_object_detected", {"type": "end_sensor"})
                    emit_fn("sensor_update", {
                        "id":           f"sensor_{sensor_id}",
                        "triggered":    event == "TRIGGERED",
                })
                continue

            is_motor_ack  = len(parts) >= 3 and parts[0] == "ACK" and parts[1].startswith("MOTOR")
            is_system_ack = len(parts) == 3 and parts[0] == "ACK" and parts[1] == "SYSTEM"
            if is_motor_ack or is_system_ack:
                running = parts[2] in ("FORWARD", "STARTED")
                label   = "DASHBOARD BUTTON" if is_motor_ack else "ARDUINO BUTTON"
                print(f"[{label.upper()}] System {'RUNNING' if running else 'STOP'}")

                if set_conveyor_state:
                    set_conveyor_state(running)
                emit_fn("conveyor_state", {"id": CONVEYOR_ID, "running": running})

                motor_running = running
                error_mgr.resolve_error("ARDUINO_SYSTEM_IS_NOT_RUNNING")
                lamp_state_updates = {}

                if lamp_state.get("green") != running:
                    lamp_state["green"] = running
                    lamp_state_updates["green"] = running

                orange_should = not running and not estop_active
                if lamp_state.get("orange") != orange_should:
                    lamp_state["orange"] = orange_should
                    lamp_state_updates["orange"] = orange_should

                if lamp_state_updates:
                    emit_fn("lamp_update", lamp_state)

                continue

            # label ack
            if len(parts) == 3 and parts[0] == "ACK" and parts[1] == "LABEL":
                category = parts[2].lower()
                emit_fn("ack_label", {"category": category})
                continue

            # UV ack
            if len(parts) == 3 and parts[0] == "ACK" and parts[1] == "UV":
                if parts[2] == "ON" or parts[2] == "OFF":
                    uv_on = parts[2] == "ON"
                    if not uv_on:
                        error_mgr.resolve_error("UV_BLOCKED")
                    if lamp_state.get('blue') != uv_on:
                        lamp_state['blue'] = uv_on
                        emit_fn('lamp_update', lamp_state)
                    continue
                if parts[2] == "BLOCKED":
                    error_mgr.raise_error("UV_BLOCKED")
                    continue
            if len(parts) == 4 and parts[0] == "ACK" and parts[3] == "DOOR_OPEN" or parts[3]=="SWITCHED":
                if parts[3] =="DOOR_OPEN" and lamp_state.get('blue'):
                    error_mgr.raise_error("UV_BLOCKED")
                else:
                    error_mgr.resolve_error("UV_BLOCKED")
                continue
            # servo events
            if len(parts) >= 3 and parts[0] == "SERVO":
                try:
                    servo_idx = int(parts[1])
                    event     = parts[2]
                except (ValueError, IndexError):
                    error_mgr.raise_error("SERIAL_PARSE_ERROR", {
                        "message":      f"SERVO parse error: {line}",
                        "message_type": "SERVO",
                        "raw":          line,
                    })
                    continue
                category = servo_index_to_category.get(servo_idx)
                if category is None:
                    error_mgr.raise_error("SERIAL_PARSE_ERROR", {
                        "message":     f"Unknown servo index {servo_idx}",
                        "servo_index": servo_idx,
                        "raw":         line,
                    })
                    continue
                if event == "OPEN":
                    if servo_idx in unwired_servos:
                        del unwired_servos[servo_idx]
                        _sync_servo_not_wired_error()
                    emit_fn("servo_update", {
                        "type":         category,
                        "active":       True,
                        "from_arduino": True,
                    })
                elif event == "OBJECT_DETECTED":
                    emit_fn("servo_object_detected", {
                        "type":  category,
                        "index": servo_idx,
                    })
                elif event in ("SORTED", "UNSORTED"):
                    if event == "UNSORTED":
                        error_mgr.raise_error("UNSORTED", {
                        "message":     f"Servo {servo_idx} ({category}) blocked at start",
                        "servo_type":  category,
                        "servo_index": servo_idx,
                        })
                        def clear_unsorted():
                            try:
                                error_mgr.resolve_error("UNSORTED")
                            except Exception:
                                pass
                        t = threading.Timer(10.0, clear_unsorted)
                        t.daemon = True
                        t.start()
                    else:
                        error_mgr.resolve_error("UNSORTED")
                    set_active_servo(None, 0.0)
                    emit_fn("servo_closed", {
                        "type":   category,
                        "index":  servo_idx,
                        "status": event.lower(),
                    })
                continue

            if parts[0] == "ERR" and len(parts) >= 4 and parts[1] == "SERVO":
                try:
                    servo_idx = int(parts[2])
                    category  = servo_index_to_category.get(servo_idx, f"servo_{servo_idx}")
                except (ValueError, IndexError):
                    servo_idx = -1
                    category  = "unknown"
                detail = ":".join(parts[3:])
                unwired_servos[servo_idx] = {
                    "category": category,
                    "detail":   detail,
                    "raw":      line,
                }
                _sync_servo_not_wired_error()
                continue

            # generic error messages
            if parts[0] == "ERR":
                error_type = parts[1] if len(parts) > 1 else "UNKNOWN"
                detail = ":".join(parts[2:]) if len(parts) > 2 else ""
                error_mgr.raise_error(f"ARDUINO_{error_type}_{detail}", {
                    "message": detail,
                    "raw": line,
                    "type": error_type,
                })
                if detail.strip().upper() == "UNKNOWN_CMD":
                    def _clear_unknown_cmd():
                        try:
                            error_mgr.resolve_error("ARDUINO_SYSTEM_UNKNOWN_CMD")
                        except Exception:
                            pass
                    t = threading.Timer(10.0, _clear_unknown_cmd)
                    t.daemon = True
                    t.start()
                continue

            if "Sorting System Ready" in line:
                continue

            error_mgr.raise_error("SERIAL_UNRECOGNIZED_LINE", {
                "message": f"Unrecognised serial line: {line}",
                "raw":     line,
            })

        except Exception as e:
            print(f"[SERIAL] read error: {e}")
            error_mgr.raise_error("SERIAL_DEVICE_UNREACHABLE", {"exception": str(e)})
            time.sleep(1)
            error_mgr.resolve_error("SERIAL_DEVICE_UNREACHABLE")




class SerialManager:
    """
    Manages the serial connection to the Arduino.

    Key design decisions
    
    • Uses threading.RLock so the reconnect thread can call connect() while
      already holding the lock (fixes the previous non-reentrant deadlock).
    • _disconnect() is the single place that tears down the connection and
      marks the object as unavailable.
    • _auto_reconnect_loop() tries every candidate port on every pass so a
      re-enumerated Arduino (different /dev/ttyACMx number) is still found.
    • After a successful reconnect the RX buffer is flushed so stale bytes
      from the previous session can't corrupt the first message.
    """
    # How long to pause between reconnect attempts (seconds)
    _RECONNECT_INTERVAL = 2.0
    # How long to wait for the Arduino to finish booting after opening the port
    _BOOT_DELAY = 2.0

    def __init__(self, baud=BAUD):
        self.baud      = baud
        self.ser       = None
        self.port      = None
        self.available = False

        # RLock lets the same thread re-enter (fixes deadlock vs plain Lock)
        self._connect_lock   = threading.RLock()
        self._stop_reconnect = False

        self._reconnect_thread = threading.Thread(
            target=self._auto_reconnect_loop, daemon=True
        )
        self._reconnect_thread.start()

    #  PORT DETECTION 

    @staticmethod
    def _is_arduino_port(device: str) -> bool:
        """Return True if the port device path looks like an Arduino."""
        return (
            "/dev/ttyACM" in device
            or "/dev/ttyUSB" in device
            or "usbmodem"   in device
            or "usbserial"  in device
            or device.startswith("COM")
        )

    def _list_candidate_ports(self) -> list:
        """Return device strings for all ports that look like an Arduino."""
        return [
            p.device
            for p in serial.tools.list_ports.comports()
            if self._is_arduino_port(p.device)
        ]

    def find_arduino_port(self) -> str | None:
        """
        Probe each candidate port and return the first one that accepts a
        connection, or None if none respond.
        """
        for port in self._list_candidate_ports():
            try:
                ser = serial.Serial(port, self.baud, timeout=0.05)
                time.sleep(self._BOOT_DELAY)
                ser.write(b"\n")
                ser.close()
                print(f"[SERIAL] Arduino found on {port}")
                return port
            except Exception:
                continue
        return None

    # INTERNAL HELPERS 

    def _disconnect(self):
        """Tear down the current connection (safe to call multiple times)."""
        with self._connect_lock:
            if self.ser is not None:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
            self.available = False

    def _open_port(self, port: str, emit_fn=None) -> bool:
        """
        Open *port*, wait for the Arduino to boot, flush stale RX bytes, and
        update internal state.  Returns True on success.
        Called with self._connect_lock already held.
        """
        error_mgr = get_error_manager(emit_fn)
        try:
            ser = serial.Serial(port, self.baud, timeout=0.05)
            time.sleep(self._BOOT_DELAY)   # wait for Arduino bootloader
            ser.reset_input_buffer()        # discard stale bytes from old session
            self.ser       = ser
            self.port      = port
            self.available = True
            print(f"[SERIAL] Connected on {port}")
            error_mgr.resolve_error("SERIAL_NOT_CONNECTED")
            return True
        except Exception as e:
            print(f"[SERIAL WARNING] Could not open {port}: {e}")
            return False

    # AUTO RECONNECT 

    def _auto_reconnect_loop(self):
        """
        Background thread.  Whenever the connection is down it scans *all*
        candidate ports (not just the first) so the Arduino is found even if
        it re-enumerates on a different /dev/ttyACMx number after being
        unplugged and plugged back in.
        """
        while not self._stop_reconnect:
            try:
                if self.serial_ok():
                    time.sleep(1.0)
                    continue

                candidates = self._list_candidate_ports()
                if not candidates:
                    time.sleep(1.0)
                    continue

                connected = False
                for port in candidates:
                    with self._connect_lock:
                        # Double-check: another thread may have connected already
                        if self.serial_ok():
                            connected = True
                            break
                        if self._open_port(port):
                            connected = True
                            break

                # Back off before the next probe regardless of outcome
                time.sleep(self._RECONNECT_INTERVAL if not connected else 1.0)

            except Exception:
                time.sleep(1.0)

    # PUBLIC API 

    def connect(self, port: str | None = None, emit_fn=None):
        error_mgr = get_error_manager(emit_fn)

        with self._connect_lock:
            if port:
                if self._open_port(port):
                    return
                explicit_failed = True
            else:
                explicit_failed = False

            # Auto-detect
            detected = self.find_arduino_port()
            if detected and self._open_port(detected):
                error_mgr.resolve_error("SERIAL_NOT_CONNECTED")
                return
            
            self.available = False

            if detected:
                # device exists but cannot be opened
                if error_mgr:
                    error_mgr.resolve_error("SERIAL_NOT_CONNECTED")
                    error_mgr.raise_error("SERIAL_DEVICE_UNREACHABLE", {
                        "port": detected,
                        "reason": "Device detected but serial open failed",
                    })
            else:
                # nothing found at all
                if error_mgr:
                    error_mgr.raise_error("SERIAL_NOT_CONNECTED", {
                        "reason": "No Arduino detected on any port",
                    })

            print("[SERIAL WARNING] Arduino not available — OFFLINE mode")

    def serial_ok(self) -> bool:
        """Return True only when the serial port is open and usable."""
        return self.ser is not None and getattr(self.ser, "is_open", False)

    def send(self, msg: str, emit_fn=None):
        """Send a newline-terminated message to the Arduino."""
        error_mgr = get_error_manager(emit_fn)

        if not self.serial_ok():
            short = msg[:50] + "..." if len(msg) > 50 else msg
            print(f"[SERIAL WARNING] write ignored — not connected: {short}")
            if error_mgr:
                error_mgr.raise_error("SERIAL_NOT_CONNECTED", {
                    "attempted_message": short,
                })
            return
        try:
            self.ser.write((msg + "\n").encode())
            print(f"[SERIAL →] {msg}")
        except Exception as e:
            print(f"[SERIAL ERROR] send failed: {e}")
            if error_mgr:
                error_mgr.raise_error("SERIAL_DEVICE_UNREACHABLE", {
                    "exception": str(e),
                    "message":   msg,
                })
            self._disconnect()   # mark as disconnected → reconnect loop kicks in

    def read_line(self) -> str | None:
        """
        Read one newline-terminated line.
        Returns None (instead of raising) when nothing is available or on error.
        """
        if not self.serial_ok():
            return None
        try:
            raw = self.ser.readline()
            return raw.decode(errors="ignore").strip() or None
        except Exception as e:
            print(f"[SERIAL] read_line error: {e}")
            self._disconnect()   # mark as disconnected → reconnect loop kicks in
            return None

    def close(self):
        """Cleanly shut down: stop the reconnect thread then close the port."""
        self._stop_reconnect = True
        self._disconnect()
        print("[SERIAL] Connection closed")