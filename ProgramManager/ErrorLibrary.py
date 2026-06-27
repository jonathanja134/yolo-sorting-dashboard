from enum import Enum

"""
SERIAL_NOT_CONNECTED         | SERIAL_DEVICE_UNREACHABLE     | SERIAL_PARSE_ERROR
SERIAL_UNRECOGNIZED_LINE     | MOTOR_FEEDBACK_MISMATCH       | SERVO_NOT_WIRED 
UNSORTED                     | ARDUINO_SYSTEM_IS_NOT_RUNNING | ARDUINO_SYSTEM_UNKNOWN_CMD      
DATABASE_CONNECTION_FAILED   | SOCKET_DISCONNECTED           | CONTROL_CONVEYOR_BLOCKED
ARDUINO_PULSE_OUT_OF_RANGE   | ESTOP_ACTIVE                  | ESTOP_CLEARED                
UNKNOWN_ERROR                | UV_BLOCKED
"""


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


ERROR_CATALOG = {
    # ─── SERIAL / CONNECTION ────────────────────────────────────────────────────
    "SERIAL_NOT_CONNECTED": {
        "code": "SERIAL_001",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERIAL,
        "title": "Serial Port Not Connected",
        "message": "Arduino is not connected. Check USB cable and port configuration.",
        "action": "Reconnect Arduino and restart the system.",
    },
    "SERIAL_DEVICE_UNREACHABLE": {
        "code": "SERIAL_003",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERIAL,
        "title": "Connection Failed",
        "message": "Arduino is not reachable, not able to read or write.",
        "action": "Check connection and restart the system.",
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
    "SERVO_NOT_WIRED": {
        "code": "SERVO_005",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERVO,
        "title": "Servo Not Wired",
        "message": "Servo is not physically connected or wiring check failed.",
        "action": "Check servo wiring and PCA9685 channel assignment.",
    },
    "UNSORTED": {
        "code": "SERVO_004",
        "severity": ErrorSeverity.WARNING,
        "source": ErrorSource.SERVO,
        "title": "Unsorted Object",
        "message": "Object was not sorted and reached the rejecting area.",
        "action": "Check tmeout settings and object path. Consider adjusting servo timing or placement.",
    },
    "SERVO_FAULT": {
        "code": "SERVO_003",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.SERVO,
        "title": "Servo Error",
        "message": "Failed to execute the servo command with Arduino.",
        "action": "Check Arduino connection and servo configuration.",
    },
    "ARDUINO_SYSTEM_IS_NOT_RUNNING": {
        "code": "SYSTEM_998",
        "severity": ErrorSeverity.WARNING,
        "source": ErrorSource.SYSTEM,
        "title": "System Not Running",
        "message": "Cannot perform action: system is not running.",
        "action": "Start the system to enable this action.",
    },
    "ARDUINO_PULSE_OUT_OF_RANGE": {
        "code": "ARDUINO_002",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.ARDUINO,
        "title": "Arduino Pulse Out of Range",
        "message": "Calculated servo pulse is out of safe range.",
        "action": "Check servo configuration and mechanical limits.",
    },
    "ARDUINO_SYSTEM_UNKNOWN_CMD": {
        "code": "ARDUINO_001",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.ARDUINO,
        "title": "Arduino Error",
        "message": "Arduino reported an error.",
        "action": "Check Arduino serial output and firmware.",
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
    "CONTROL_CONVEYOR_BLOCKED": {
        "code": "SYSTEM_003",
        "severity": ErrorSeverity.ERROR,
        "source": ErrorSource.CONVEYOR,
        "title": "Conveyor Control Blocked",
        "message": "Cannot control conveyor: Arduino is disconnected.",
        "action": "Reconnect Arduino before starting or stopping conveyors.",
    },
    "UV_BLOCKED": {
        "code": "SYSTEM_006",
        "severity": ErrorSeverity.WARNING,
        "source": ErrorSource.SYSTEM,
        "title": "UV Light Blocked",
        "message": "UV light is blocked .",
        "action": "Ensure UV door are closed and system is running",
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