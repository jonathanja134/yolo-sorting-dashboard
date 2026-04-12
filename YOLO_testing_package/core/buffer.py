"""
Detection buffer for YOLO NCNN inference.

Accumulates per-frame detections in the format produced by the main
inference loop:  (x1, y1, x2, y2, conf, cid)

Labels mirror the order used in the NCNN script so class IDs map
correctly without any translation layer.
"""

from collections import defaultdict
from typing import NamedTuple

LABELS = [
    "Applicator white/bleu",
    "Applicator white/gray",
    "Applicator gray",
    "Applicator Orange /white",
    "Applicator pink",
    "Inhaler bleu",
    "Inhaler white",
    "Canister",
]


class Detection(NamedTuple):
    """Single detection exactly as produced by the inference loop."""
    x1:   int
    y1:   int
    x2:   int
    y2:   int
    conf: float
    cid:  int

    @property
    def label(self) -> str:
        return LABELS[self.cid]


class DetectionBuffer:
    """
    Sliding window that collects the highest-confidence detection per
    frame.  Call :meth:`push` once per inference tick, then
    :meth:`compute_result` to get a verdict.
    """

    def __init__(self, max_frames: int = 30):
        self.max_frames = max_frames
        self._frames: list[list[Detection]] = []

    # ------------------------------------------------------------------
    def push(self, detections: list[Detection]) -> None:
        """Append one frame's worth of detections (may be empty)."""
        self._frames.append(list(detections))
        if len(self._frames) > self.max_frames:
            self._frames.pop(0)

    # ------------------------------------------------------------------
    def compute_result(self, min_frames: int = 5) -> dict:
        """
        Return a result dict:
          winner          – label with the most votes  (or None)
          confidence      – fraction of votes won  (0.0-1.0)
          avg_conf        – mean detector confidence for the winner
          vote_counts     – {label: count} across all frames
          low_confidence  – True when fewer than min_frames have any detection
        """
        return compute_result(
            self._votes(), min_frames=min_frames
        )

    def _votes(self) -> list[tuple[str, float]]:
        """One (label, conf) vote per frame – the top detection only."""
        votes = []
        for frame in self._frames:
            if frame:
                best = max(frame, key=lambda d: d.conf)
                votes.append((best.label, best.conf))
        return votes

    # ------------------------------------------------------------------
    def clear(self) -> None:
        self._frames.clear()

    def __len__(self) -> int:
        return len(self._frames)


# ----------------------------------------------------------------------
# Stateless helper – used by DetectionBuffer and the old-style tests
# ----------------------------------------------------------------------

def compute_result(
    votes: list[tuple[str, float]],
    min_frames: int = 5,
) -> dict:
    """
    Aggregate a list of (label, conf) votes.

    Parameters
    ----------
    votes       : list of (label_string, float_confidence)
    min_frames  : minimum number of votes required before the result
                  is considered reliable

    Returns
    -------
    dict with keys:
        winner, confidence, avg_conf, vote_counts, low_confidence
    """
    result: dict = {
        "winner":         None,
        "confidence":     0.0,
        "avg_conf":       0.0,
        "vote_counts":    {},
        "low_confidence": True,
    }

    if not votes:
        return result

    count_map:   defaultdict[str, int]   = defaultdict(int)
    conf_map:    defaultdict[str, float] = defaultdict(float)

    for label, conf in votes:
        count_map[label] += 1
        conf_map[label]  += conf

    result["vote_counts"] = dict(count_map)

    winner     = max(count_map, key=count_map.__getitem__)
    win_votes  = count_map[winner]
    total      = len(votes)

    result["winner"]         = winner
    result["confidence"]     = win_votes / total
    result["avg_conf"]       = conf_map[winner] / win_votes
    result["low_confidence"] = total < min_frames

    return result