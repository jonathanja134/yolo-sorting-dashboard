# ── YOLO LABELS ─────────────────────────────────────────────

labels = [
    "Applicator white/blue",
    "Applicator white/gray",
    "Applicator gray",
    "Applicator orange/white",
    "Applicator pink",
    "Inhaler blue",
    "Inhaler white",
    "Canister"
]
num_classes = len(labels)

bbox_colors = [
    (173, 216, 230),
    (211, 211, 211),
    (105, 105, 105),
    (255, 165, 0),
    (255, 192, 203),
    (0, 0, 128),
    (255, 255, 255),
    (255, 0, 0),
]

# ── MAPPINGS ───────────────────────────────────────────────

LABEL_TO_CATEGORY = {
    0: "applicator",
    1: "applicator",
    2: "applicator",
    3: "applicator",
    4: "applicator",
    5: "inhaler",
    6: "inhaler",
    7: "canister",
}

SERVO_INDEX_TO_CATEGORY = {
    1: "canister",
    2: "sharps",
    3: "applicator",
    4: "inhaler",
}

SERVO_LABEL = {
    "canister":   "Servo 1 – Canister",
    "sharps":     "Servo 2 – Sharps / Apply Pen / Syringes / Bag",
    "applicator": "Servo 3 – Applicator",
    "inhaler":    "Servo 4 – Inhaler",
}

SERVO_COLOR = {
    "canister":   (0, 200, 255),
    "sharps":     (0, 80, 255),
    "applicator": (200, 255, 80),
    "inhaler":    (80, 255, 200),
}

# ── MODEL / INFERENCE SETTINGS ─────────────────────────────

input_size = 640
conf_thresh = 0.6
nms_thresh = 0.45

# ── BUFFER SETTINGS ────────────────────────────────────────

min_frames = 5
gap_limit = 20