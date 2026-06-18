# ─────────────────────  Config ──────────────────────────

# ── YOLO LABELS ─────────────────────────────────────────────
# can be replaced by "yolo11sV0", "yolo11nV1", "yolo26nV2", "yolo26nV3" or a personal model inside /my_model_ncnn_model

Yolo_model = "yolo26nV3"

# ── YOLO LABELS ─────────────────────────────────────────────

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

# ── MAPPINGS ───────────────────────────────────────────────

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

# ── MODEL / INFERENCE SETTINGS ─────────────────────────────

input_size = 320
conf_thresh = 0.8
nms_thresh = 0.45

# ── BUFFER SETTINGS ────────────────────────────────────────

min_frames = 20
gap_limit = 20

# ── SERIAL SETTINGS ────────────────────────────────────────
BAUD = 115200
PORT = "/dev/ttyACM0"
SOCKET_PORT = 5500

# ── CONVEYOR PIN MAPPING ──────────────────────────────────
# Each conveyor has its own Arduino pin
CONVEYOR_PINS = {
    "conveyor_1": 10,  # NOTE:  Conveyor 1 and 2 currently driven by Pin 10 in arduino since no need for dependency management.
    "conveyor_2": 9,  
    "conveyor_3": 8,   
}


def normalize_conveyor_db_id(raw, default=1):
    """Numeric id for DB / dashboard DOM (1, 2, 3). Accepts 1, '1', 'conveyor_1'."""
    if raw is None:
        return default
    if isinstance(raw, int):
        return raw
    s = str(raw).strip().lower()
    if s.startswith("conveyor_"):
        return int(s.split("_", 1)[1])
    return int(s)


def conveyor_socket_id(db_id):
    """String id for Pi motor state (conveyor_1, …)."""
    return f"conveyor_{int(db_id)}"