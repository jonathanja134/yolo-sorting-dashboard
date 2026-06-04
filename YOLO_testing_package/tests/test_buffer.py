"""
Tests for core.buffer

Detection format mirrors the inference loop in the NCNN script:
    (x1, y1, x2, y2, conf, cid)

Class IDs map to LABELS in the same order as the script's labels list.
"""

import pytest
from core.buffer import Detection, DetectionBuffer, compute_result, LABELS

# ── convenient cid aliases matching the script's label order ──────────
CID_APP_WHITE_BLEU  = 0   # "Applicator white/bleu"
CID_APP_WHITE_GRAY  = 1   # "Applicator white/gray"
CID_APP_GRAY        = 2   # "Applicator gray"
CID_APP_ORANGE      = 3   # "Applicator Orange /white"
CID_APP_PINK        = 4   # "Applicator pink"
CID_INHALER_BLEU    = 5   # "Inhaler bleu"
CID_INHALER_WHITE   = 6   # "Inhaler white"
CID_CANISTER        = 7   # "Canister"


# ── Detection helper ──────────────────────────────────────────────────

def make_det(cid: int, conf: float = 0.9) -> Detection:
    """Return a Detection with a plausible 640x480 bounding box."""
    return Detection(x1=100, y1=80, x2=300, y2=260, conf=conf, cid=cid)


# ══════════════════════════════════════════════════════════════════════
# Detection namedtuple
# ══════════════════════════════════════════════════════════════════════

class TestDetection:
    def test_label_property_maps_cid_to_name(self):
        d = make_det(CID_CANISTER)
        assert d.label == "Canister"

    def test_all_cids_resolve_to_correct_labels(self):
        for cid, expected in enumerate(LABELS):
            assert make_det(cid).label == expected

    def test_fields_accessible_by_name(self):
        d = make_det(CID_INHALER_BLEU, conf=0.75)
        assert d.conf == pytest.approx(0.75)
        assert d.cid  == CID_INHALER_BLEU
        assert d.x1 == 100 and d.y2 == 260


# ══════════════════════════════════════════════════════════════════════
# compute_result  (stateless helper)
# ══════════════════════════════════════════════════════════════════════

class TestComputeResult:

    # ── majority vote ─────────────────────────────────────────────────
    def test_majority_winner_canister(self):
        votes = [
            ("Canister", 0.90),
            ("Canister", 0.85),
            ("Inhaler bleu", 0.80),
        ]
        r = compute_result(votes, min_frames=2)
        assert r["winner"] == "Canister"

    def test_majority_confidence_is_fraction_of_votes(self):
        votes = [
            ("Canister", 0.90),
            ("Canister", 0.85),
            ("Inhaler bleu", 0.80),
        ]
        r = compute_result(votes, min_frames=2)
        assert r["confidence"] == pytest.approx(2 / 3)

    def test_avg_conf_averages_winner_detector_scores(self):
        votes = [
            ("Canister", 0.90),
            ("Canister", 0.80),
            ("Inhaler bleu", 0.95),
        ]
        r = compute_result(votes, min_frames=2)
        assert r["avg_conf"] == pytest.approx(0.85)

    # ── vote_counts ───────────────────────────────────────────────────
    def test_vote_counts_all_labels_present(self):
        votes = [
            ("Canister",    0.9),
            ("Canister",    0.8),
            ("Inhaler bleu", 0.7),
        ]
        r = compute_result(votes, min_frames=2)
        assert r["vote_counts"]["Canister"]    == 2
        assert r["vote_counts"]["Inhaler bleu"] == 1

    # ── low_confidence flag ───────────────────────────────────────────
    def test_low_confidence_when_below_min_frames(self):
        votes = [("Canister", 0.9)]
        r = compute_result(votes, min_frames=5)
        assert r["low_confidence"] is True

    def test_not_low_confidence_when_at_min_frames(self):
        votes = [("Canister", 0.9)] * 5
        r = compute_result(votes, min_frames=5)
        assert r["low_confidence"] is False

    # ── edge cases ────────────────────────────────────────────────────
    def test_empty_votes_returns_safe_defaults(self):
        r = compute_result([], min_frames=1)
        assert r["winner"]         is None
        assert r["confidence"]     == 0.0
        assert r["low_confidence"] is True

    def test_single_class_wins_unanimously(self):
        votes = [("Applicator pink", 0.88)] * 10
        r = compute_result(votes, min_frames=5)
        assert r["winner"]     == "Applicator pink"
        assert r["confidence"] == pytest.approx(1.0)

    def test_tie_votes_return_first_seen_winner(self):
        votes = [
            ("Canister", 0.90),
            ("Inhaler bleu", 0.92),
            ("Canister", 0.80),
            ("Inhaler bleu", 0.85),
        ]
        r = compute_result(votes, min_frames=1)
        assert r["confidence"] == pytest.approx(0.5)
        assert r["vote_counts"] == {"Canister": 2, "Inhaler bleu": 2}
        assert r["winner"] in {"Canister", "Inhaler bleu"}


# ══════════════════════════════════════════════════════════════════════
# DetectionBuffer  (stateful, frame-by-frame)
# ══════════════════════════════════════════════════════════════════════

class TestDetectionBuffer:

    def _feed(self, buf: DetectionBuffer, cid: int,
              n: int, conf: float = 0.9) -> None:
        """Push n frames each containing one detection of class cid."""
        for _ in range(n):
            buf.push([make_det(cid, conf)])

    # ── basic accumulation ────────────────────────────────────────────
    def test_push_increments_frame_count(self):
        buf = DetectionBuffer()
        buf.push([make_det(CID_CANISTER)])
        assert len(buf) == 1

    def test_empty_frame_still_counted(self):
        buf = DetectionBuffer()
        buf.push([])
        assert len(buf) == 1

    def test_max_frames_caps_buffer_length(self):
        buf = DetectionBuffer(max_frames=5)
        for _ in range(10):
            buf.push([make_det(CID_CANISTER)])
        assert len(buf) == 5

    # ── voting via DetectionBuffer.compute_result ─────────────────────
    def test_majority_class_wins(self):
        buf = DetectionBuffer()
        self._feed(buf, CID_CANISTER,     n=4)
        self._feed(buf, CID_INHALER_BLEU, n=2)
        r = buf.compute_result(min_frames=3)
        assert r["winner"] == "Canister"

    def test_empty_frames_do_not_cast_votes(self):
        """Empty frames count toward min_frames but not toward votes."""
        buf = DetectionBuffer()
        self._feed(buf, CID_CANISTER, n=3)
        buf.push([])   # empty – no vote cast
        buf.push([])
        r = buf.compute_result(min_frames=2)
        assert r["winner"]     == "Canister"
        assert r["confidence"] == pytest.approx(1.0)  # 3 votes, all Canister

    def test_best_detection_per_frame_is_used(self):
        """When multiple detections appear in one frame, highest conf wins."""
        buf = DetectionBuffer()
        frame = [
            make_det(CID_INHALER_WHITE, conf=0.55),
            make_det(CID_CANISTER,      conf=0.92),  # ← should win
        ]
        for _ in range(5):
            buf.push(frame)
        r = buf.compute_result(min_frames=3)
        assert r["winner"] == "Canister"

    def test_low_confidence_when_not_enough_frames(self):
        buf = DetectionBuffer()
        self._feed(buf, CID_CANISTER, n=2)
        r = buf.compute_result(min_frames=5)
        assert r["low_confidence"] is True

    def test_clear_resets_buffer(self):
        buf = DetectionBuffer()
        self._feed(buf, CID_CANISTER, n=5)
        buf.clear()
        assert len(buf) == 0
        r = buf.compute_result(min_frames=1)
        assert r["winner"] is None

    # ── applicator classes (non-canister/inhaler) ─────────────────────
    def test_applicator_orange_detected_over_multiple_frames(self):
        buf = DetectionBuffer()
        self._feed(buf, CID_APP_ORANGE, n=6, conf=0.78)
        r = buf.compute_result(min_frames=5)
        assert r["winner"]     == "Applicator Orange /white"
        assert r["avg_conf"]   == pytest.approx(0.78)
        assert r["confidence"] == pytest.approx(1.0)