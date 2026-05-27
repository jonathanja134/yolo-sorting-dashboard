"""
ErrorManager.py – Centralized error definitions and handlers for the sorting system.

Severity rules (dashboard):
  INFO     → log sidebar only (system_log)
  WARNING+ → banner (cumulative single line) + log sidebar (system_error)
"""

from enum import Enum
from datetime import datetime


class ErrorSeverity(Enum):
    """Error severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorSource(Enum):
    """Error source categories."""
    ARDUINO = "arduino"
    SERIAL = "serial"
    SYSTEM = "system"
    SERVO = "servo"
    CONVEYOR = "conveyor"
    YOLO = "yolo"
    BUFFER = "buffer"
    DATABASE = "database"


# ══════════════════════════════════════════════════════════════════════════════
# Error Catalog
# ══════════════════════════════════════════════════════════════════════════════

"""
SERIAL_NOT_CONNECTED            |  SERIAL_PORT_NOT_FOUND | SERIAL_CONNECT_FAILED
SERIAL_READ_ERROR               |  SERIAL_WRITE_ERROR    | SERIAL_PARSE_ERROR
SERIAL_UNRECOGNIZED_LINE        |  MOTOR_FAULT           | SERVO_NOT_WIRED 
SERVO_FAULT                     |  SERVO_TIMEOUT         | SERVO_BLOCKED   
SERVO_INVALID_INDEXSENSOR_FAULT |  ARDUINO_ERR           | ARDUINO_INFO
MODEL_LOAD_FAILED               |  LOW_CONFIDENCE        | UNRECOGNIZED_OBJECT
DATABASE_CONNECTION_FAILED      |  SOCKET_DISCONNECTED   | CONFIGURATION_ERROR
CONTROL_CONVEYOR_BLOCKED        |  UNKNOWN_ERROR
"""


ERROR_CATALOG = {
    # ─── SERIAL / CONNECTION ────────────────────────────────────────────────────
    "SERIAL_NOT_CONNECTED": {
        "code": "SERIAL_001",
        "severity": ErrorSeverity.CRITICAL,
        "source": ErrorSource.SERIAL,
        "title": "Serial Port Not Connected",
        "message": "Arduino is not connected. Check USB cable and port configuration.",
        "action": "Reconnect Arduino and restart the system.",
    },
    "SERIAL_PORT_NOT_FOUND": {
        "code": "SERIAL_002",
        "severity": ErrorSeverity.CRITICAL,
        "source": ErrorSource.SERIAL,
        "title": "Arduino Port Not Found",
        "message": "No Arduino detected on configured port.",
        "action": "Verify port configuration and Arduino connection.",
    },
    "SERIAL_CONNECT_FAILED": {
        "code": "SERIAL_003",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERIAL,
        "title": "Connection Failed",
        "message": "Failed to establish serial connection.",
        "action": "Check port is not in use by another application.",
    },
    "SERIAL_READ_ERROR": {
        "code": "SERIAL_004",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERIAL,
        "title": "Serial Read Error",
        "message": "Error reading from serial port.",
        "action": "Check connection and restart if persistent.",
    },
    "SERIAL_WRITE_ERROR": {
        "code": "SERIAL_005",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERIAL,
        "title": "Serial Write Error",
        "message": "Failed to send command to Arduino.",
        "action": "Check connection and resend command.",
    },
    "SERIAL_PARSE_ERROR": {
        "code": "SERIAL_006",
        "severity": ErrorSeverity.WARNING,
        "source": ErrorSource.SERIAL,
        "title": "Serial Parse Error",
        "message": "Received invalid message format from Arduino.",
        "action": "Check Arduino firmware for issues.",
    },
    "SERIAL_UNRECOGNIZED_LINE": {
        "code": "SERIAL_007",
        "severity": ErrorSeverity.WARNING,
        "source": ErrorSource.SERIAL,
        "title": "Unrecognised Serial Message",
        "message": "Received an unrecognised line from Arduino.",
        "action": "Check serial protocol and firmware version.",
    },
    # ─── ARDUINO HARDWARE ─────────────────────────────────────────────────────
    "MOTOR_FAULT": {
        "code": "MOTOR_001",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.CONVEYOR,
        "title": "Motor Fault",
        "message": "Conveyor motor encountered a fault.",
        "action": "Check motor connections and power supply.",
    },
    "SERVO_NOT_WIRED": {
        "code": "SERVO_005",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERVO,
        "title": "Servo Not Wired",
        "message": "Servo is not physically connected or wiring check failed.",
        "action": "Check servo wiring and PCA9685 channel assignment.",
    },
    "SERVO_FAULT": {
        "code": "SERVO_003",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERVO,
        "title": "Servo Error",
        "message": "Failed to execute the servo command with Arduino.",
        "action": "Check Arduino connection and servo configuration.",
    },
    "SERVO_TIMEOUT": {
        "code": "SERVO_001",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERVO,
        "title": "Servo Close Timeout",
        "message": "Servo closed on timeout — object may not have passed.",
        "action": "Check object path and servo mechanism.",
    },
    "SERVO_BLOCKED": {
        "code": "SERVO_002",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERVO,
        "title": "Servo Blocked",
        "message": "Servo blocked at start of cycle.",
        "action": "Clear obstruction and retry.",
    },
    "SERVO_INVALID_INDEX": {
        "code": "SERVO_004",
        "severity": ErrorSeverity.WARNING,
        "source": ErrorSource.SERVO,
        "title": "Invalid Servo Index",
        "message": "Arduino reported an unknown servo index.",
        "action": "Check servo wiring and firmware mapping.",
    },
    "SENSOR_FAULT": {
        "code": "SENSOR_001",
        "severity": ErrorSeverity.WARNING,
        "source": ErrorSource.ARDUINO,
        "title": "Sensor Malfunction",
        "message": "Arduino sensor reported malfunction.",
        "action": "Check sensor connections and alignment.",
    },
    "ARDUINO_ERR": {
        "code": "ARDUINO_001",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.ARDUINO,
        "title": "Arduino Error",
        "message": "Arduino reported an error.",
        "action": "Check Arduino serial output and firmware.",
    },
    "ARDUINO_INFO": {
        "code": "ARDUINO_INFO",
        "severity": ErrorSeverity.INFO,
        "source": ErrorSource.ARDUINO,
        "title": "Arduino Info",
        "message": "Information from Arduino.",
        "action": "None.",
    },
    # ─── YOLO / DETECTION ───────────────────────────────────────────────────────
    "MODEL_LOAD_FAILED": {
        "code": "YOLO_001",
        "severity": ErrorSeverity.CRITICAL,
        "source": ErrorSource.YOLO,
        "title": "Model Load Failed",
        "message": "Failed to load YOLO model.",
        "action": "Check model file paths and file integrity.",
    },
    # ─── BUFFER / DETECTION LOGIC ───────────────────────────────────────────────
    "LOW_CONFIDENCE": {
        "code": "BUFFER_001",
        "severity": ErrorSeverity.INFO,
        "source": ErrorSource.BUFFER,
        "title": "Low Confidence Detection",
        "message": "Detection confidence below threshold.",
        "action": "None — detection rejected, collection continues.",
    },
    "UNRECOGNIZED_OBJECT": {
        "code": "BUFFER_002",
        "severity": ErrorSeverity.INFO,
        "source": ErrorSource.BUFFER,
        "title": "Unrecognized Object",
        "message": "Object could not be classified.",
        "action": "Remove or reposition the object.",
    },
    # ─── DATABASE ─────────────────────────────────────────────────────────────
    "DATABASE_CONNECTION_FAILED": {
        "code": "DATABASE_001",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.DATABASE,
        "title": "Database Connection Failed",
        "message": "Failed to connect to database.",
        "action": "Check database availability and credentials.",
    },
    # ─── SYSTEM / DASHBOARD ───────────────────────────────────────────────────
    "SOCKET_DISCONNECTED": {
        "code": "SYSTEM_001",
        "severity": ErrorSeverity.WARNING,
        "source": ErrorSource.SYSTEM,
        "title": "Dashboard Disconnected",
        "message": "SocketIO connection to dashboard lost.",
        "action": "Attempting to reconnect automatically.",
    },
    "CONFIGURATION_ERROR": {
        "code": "SYSTEM_002",
        "severity": ErrorSeverity.CRITICAL,
        "source": ErrorSource.SYSTEM,
        "title": "Configuration Error",
        "message": "Invalid system configuration.",
        "action": "Check configuration file and settings.",
    },
    "CONTROL_CONVEYOR_BLOCKED": {
        "code": "SYSTEM_003",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.CONVEYOR,
        "title": "Conveyor Control Blocked",
        "message": "Cannot control conveyor: Arduino is disconnected.",
        "action": "Reconnect Arduino before starting or stopping conveyors.",
    },
    "ESTOP_ACTIVE": {
    "code": "SYSTEM_004",
    "severity": ErrorSeverity.CRITICAL,
    "source": ErrorSource.SYSTEM,
    "title": "Emergency Stop Active",
    "message": "E-stop triggered — motor and all servos Stopped immediately.",
    "action": "Clear the E-stop signal to resume. System must be restarted manually.",
    },
    "ESTOP_CLEARED": {
        "code": "SYSTEM_005",
        "severity": ErrorSeverity.CRITICAL,
        "source": ErrorSource.SYSTEM,
        "title": "Emergency Stop Cleared",
        "message": "E-stop signal restored. System is ready to restart.",
        "action": "Press Start or send MOTOR:FORWARD to resume.",
    },
    "UNKNOWN_ERROR": {
        "code": "SYSTEM_999",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SYSTEM,
        "title": "Unknown Error",
        "message": "An unexpected error occurred.",
        "action": "Check logs for more details.",
    },  
}


def _severity_value(severity) -> str:
    return severity.value if isinstance(severity, ErrorSeverity) else severity


# ══════════════════════════════════════════════════════════════════════════════
# Error Manager Class
# ══════════════════════════════════════════════════════════════════════════════

class ErrorManager:
    """Central error handler and tracker."""

    def __init__(self, emit_fn=None):
        self.emit_fn = emit_fn
        self.active_errors = {}   # error_key -> error_dict
        self.error_history = []
        self._pending = []        # [(event, payload), ...] before emit_fn is set

    def set_emit_fn(self, emit_fn):
        """Attach dashboard emit callback and flush queued events."""
        self.emit_fn = emit_fn
        self.replay_pending()

    def get_error_def(self, error_code: str) -> dict:
        return ERROR_CATALOG.get(error_code, ERROR_CATALOG["UNKNOWN_ERROR"])

    def _build_error_obj(self, error_code: str, details=None) -> dict:
        if error_code not in ERROR_CATALOG:
            error_code = "UNKNOWN_ERROR"

        error_def = ERROR_CATALOG[error_code]
        message = error_def["message"]
        if details and details.get("message"):
            message = details["message"]

        return {
            "error_key": error_code,
            "code": error_def["code"],
            "title": error_def["title"],
            "message": message,
            "action": error_def["action"],
            "severity": _severity_value(error_def["severity"]),
            "source": error_def["source"].value,
            "timestamp": datetime.now().isoformat(),
            "details": details or {},
        }

    def _emit_or_queue(self, event: str, payload: dict):
        if self.emit_fn:
            self.emit_fn(event, payload)
        else:
            self._pending.append((event, payload))

    def replay_pending(self):
        """Emit queued events and refresh active banner errors after connect."""
        if not self.emit_fn:
            return

        pending = list(self._pending)
        self._pending.clear()
        replayed_keys = set()
        for event, payload in pending:
            self.emit_fn(event, payload)
            if event == "system_error":
                replayed_keys.add(payload.get("error_key"))

        for key, err in self.active_errors.items():
            if (
                err["severity"] != ErrorSeverity.INFO.value
                and key not in replayed_keys
            ):
                self.emit_fn("system_error", err)

    def raise_error(self, error_code: str, details: dict = None) -> dict:
        """Raise WARNING+ / ERROR / CRITICAL — banner + log."""
        if error_code not in ERROR_CATALOG:
            error_code = "UNKNOWN_ERROR"

        error_def = ERROR_CATALOG[error_code]
        if error_def["severity"] == ErrorSeverity.INFO:
            return self.log_info(error_code, details)

        error_obj = self._build_error_obj(error_code, details)
        self.active_errors[error_code] = error_obj
        self.error_history.append(error_obj)
        self._emit_or_queue("system_error", error_obj)
        print(f"[ERROR] {error_obj['code']} - {error_obj['title']}: {error_obj['message']}")
        return error_obj

    def log_info(self, error_code: str, details: dict = None) -> dict:
        """Log INFO severity — sidebar only, not banner."""
        if error_code not in ERROR_CATALOG:
            error_code = "UNKNOWN_ERROR"

        error_obj = self._build_error_obj(error_code, details)
        self.error_history.append(error_obj)
        self._emit_or_queue("system_log", error_obj)
        print(f"[INFO] {error_obj['code']} - {error_obj['title']}: {error_obj['message']}")
        return error_obj

    def resolve_error(self, error_code: str):
        if error_code in self.active_errors:
            self.active_errors.pop(error_code)
            self._emit_or_queue("error_resolved", {
                "error_key": error_code,
                "code": ERROR_CATALOG.get(error_code, ERROR_CATALOG["UNKNOWN_ERROR"])["code"],
                "timestamp": datetime.now().isoformat(),
            })
            print(f"[RESOLVED] {error_code}")

    def has_critical_error(self) -> bool:
        for error in self.active_errors.values():
            if error["severity"] == ErrorSeverity.CRITICAL.value:
                return True
        return False

    def get_active_errors(self) -> list:
        return list(self.active_errors.values())

    def get_error_history(self, limit: int = 100) -> list:
        return self.error_history[-limit:]


_global_error_manager = None


def get_error_manager(emit_fn=None) -> ErrorManager:
    global _global_error_manager
    if _global_error_manager is None:
        _global_error_manager = ErrorManager(emit_fn)
    elif emit_fn:
        _global_error_manager.set_emit_fn(emit_fn)
    return _global_error_manager
