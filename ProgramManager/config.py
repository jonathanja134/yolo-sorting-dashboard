# ─────────────────────  Config ──────────────────────────

# ── YOLO LABELS 
# can be replaced by "yolo11sV0", "yolo11nV1", "yolo26nV2", "yolo26nV3" or a personal model inside /my_model_ncnn_model

Yolo_model = "yolo26nV3.2"

# ── YOLO LABELS 

labels = [
    "Applicator A",
    "Applicator orange",
    "Applicator pink",
    "Appli Pen",
    "Canister",
    "Inhaler",
    "Seringe",
    "T-slim"
]
num_classes = len(labels)

bbox_colors = [
(255, 255, 255),  # white
(150, 200, 255),  # light orange
(203, 192, 255),  # pink
(139, 0, 0),      # dark blue
(211, 211, 211),  # light gray
(230, 216, 173),  # light blue
(0, 255, 255),    # yellow
(42, 42, 165),    # brown
]

DEVICE_COLORS = {
    "canister":   (211, 211, 211),# light blue
    "chemical":   (42, 42, 165), # dark blue
    "applicator": (230, 216, 173),# light blue
    "inhaler":    (139, 0, 0),
}

# ── MAPPINGS 

LABEL_TO_CATEGORY = {
    0: "applicator",
    1: "applicator",
    2: "applicator",
    3: "chemical",
    4: "canister",
    5: "inhaler",
    6: "chemical",
    7: "chemical",
}

SERVO_INDEX_TO_CATEGORY = {
    1: "canister",
    2: "chemical",
    3: "applicator",
    4: "inhaler",
}

SERVO_LABEL = {
    "canister":   "Servo 1 – Canister",
    "chemical":   "Servo 2 – Chemical",
    "applicator": "Servo 3 – Applicator",
    "inhaler":    "Servo 4 – Inhaler",
}

SERVO_COLOR = {
    "canister":   (0, 200, 255),
    "chemical":   (0, 80, 255),
    "applicator": (200, 255, 80),
    "inhaler":    (80, 255, 200),
}

# ── MODEL / INFERENCE SETTINGS 

input_size = 320
conf_thresh = 0.5
nms_thresh = 0.45

# ── BUFFER SETTINGS 

min_frames = 10
gap_limit = 20

# ── SERIAL SETTINGS 
BAUD = 115200
PORT = "/dev/ttyACM0"
SOCKET_PORT = 5000
# Use 127.0.0.1 (not localhost) so Pi with dashboard connection worksion works with no Ethernet/Wi‑Fi
DASHBOARD_URL = "http://127.0.0.1:5000"

# ── CONVEYOR (single physical motor, pin 10) ──
CONVEYOR_ID = "conveyor_1"
CONVEYOR_PIN = 10
CONVEYOR_PINS = {CONVEYOR_ID: CONVEYOR_PIN}

# ── CONVEYOR 1 centre-trigger window
CENTER_X_MIN = 130   
CENTER_X_MAX = 190  
CONVEYOR_STOP_COOLDOWN = 1.5  # seconds between stop commands

def normalize_conveyor_db_id(raw, default=1):
    """DB / dashboard DOM id — always 1 (conveyor_1)."""
    return 1


def conveyor_socket_id(db_id=None):
    """String id for Pi motor state."""
    return CONVEYOR_ID