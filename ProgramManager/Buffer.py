"""
Buffer.py – Adaptive majority-vote detection buffer.

Encapsulates all buffer state and commit logic.
Dependencies (serial send, socket emit, active-servo state) are injected
via the BufferManager constructor so this module stays decoupled from
yolo_reader.py globals.

Usage in yolo_reader.py:
    from ProgramManager.Buffer import BufferManager

    buffer_mgr = BufferManager(
        min_frames       = args.min_frames,
        gap_limit        = args.gap_limit,
        emit_fn          = _async_emit,          # fn(event, data)
        serial_send_fn   = serial.send,          # fn(str)
        get_active_servo = lambda: (active_servo, active_servo_until),
        set_active_servo = lambda cat, t: ...,   # sets active_servo / _until
    )

    # In the inference loop:
    buffer_mgr.add(category, weight=confidence)   # detection present
    buffer_mgr.no_detection()                     # no detection this frame

    # On sensor RESET:
    buffer_mgr.handle_reset()

    # On sensor CLEAR (keyboard sim):
    buffer_mgr.handle_clear()
"""

import threading
import time
from collections import Counter


class DetectionBuffer:
    """
    Low-level vote accumulator.
    Tracks per-frame category votes, gap counter, and collecting flag.
    All methods must be called with the caller holding buf_lock.
    """

    def __init__(self):
        self.votes: list[tuple[str, float]] = []
        self.gap_counter: int = 0
        self.collecting: bool = False

    def reset(self):
        self.votes       = []
        self.gap_counter = 0
        self.collecting  = True

    def add(self, category: str, weight: float = 1.0):
        self.votes.append((category, weight))
        self.gap_counter = 0

    def stop(self):
        self.collecting = False

    # ── Read-only helpers ──────────────────────────────────────────────────────

    @property
    def frame_count(self) -> int:
        return len(self.votes)

    def snapshot_votes(self) -> list[str]:
        """Return a plain list of category names (no weights)."""
        return [v[0] for v in self.votes]


# ─────────────────────────────────────────────────────────────────────────────

class BufferManager:
    """
    High-level manager that wraps DetectionBuffer with:
      - majority-vote commit logic
      - gap-limit auto-commit
      - SocketIO emit (injected)
      - serial send (injected)
      - active-servo state update (injected)
    """

    def __init__(
        self,
        min_frames:       int,
        gap_limit:        int,
        emit_fn,           # callable(event: str, data: dict)
        serial_send_fn,    # callable(message: str)
        get_active_servo,  # callable() → (category | None, until_ts: float)
        set_active_servo,  # callable(category | None, until_ts: float)
    ):
        self._min_frames       = min_frames
        self._gap_limit        = gap_limit
        self._emit             = emit_fn
        self._serial_send      = serial_send_fn
        self._get_active_servo = get_active_servo
        self._set_active_servo = set_active_servo

        self._buf  = DetectionBuffer()
        self._lock = threading.Lock()

    # ── Public API (called from yolo_reader.py) ────────────────────────────────

    def add(self, category: str, weight: float = 1.0):
        """Record a detection for this frame."""
        with self._lock:
            if not self._buf.collecting:
                return
            self._buf.add(category, weight)
        self._emit_state()

    def no_detection(self):
        """Record that this frame had no detection above threshold."""
        with self._lock:
            if not self._buf.collecting:
                return
            self._buf.gap_counter += 1
            gap = self._buf.gap_counter
        self._emit_state()

        if gap >= self._gap_limit:
            print("[BUFFER] gap limit reached — auto-commit")
            with self._lock:
                self._buf.stop()
            self._trigger_commit()

    def handle_reset(self):
        """
        Called on SENSOR:RESET:TRIGGERED.
        Commits any in-progress buffer, then starts a fresh collection window.
        """
        with self._lock:
            has_enough     = self._buf.frame_count >= self._min_frames
            was_collecting = self._buf.collecting
            self._buf.stop()

        if was_collecting and has_enough:
            print(f"[BUFFER] reset → committing {self._buf.frame_count} frames")
            self._trigger_commit()
        else:
            print(f"[BUFFER] reset → skipping "
                  f"({self._buf.frame_count}/{self._min_frames} frames)")

        with self._lock:
            self._buf.reset()
        print("[BUFFER] reset — collecting")
        self._emit_state()

    def handle_clear(self):
        """
        Called on keyboard 'C' / SENSOR CLEAR.
        Stops collecting and commits whatever was gathered.
        """
        with self._lock:
            collecting = self._buf.collecting
            if collecting:
                self._buf.stop()

        if collecting:
            self._trigger_commit()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _trigger_commit(self):
        threading.Thread(target=self._commit, daemon=True).start()

    def _commit(self):
        with self._lock:
            result = self._compute_result(self._buf.votes)
            self._buf.collecting  = False
            self._buf.gap_counter = 0

        if result is None:
            print("[COMMIT] empty buffer — skipped")
            return

        print(f"[COMMIT] {result}")

        if result["low_confidence"]:
            print("[COMMIT] low confidence")
            self._emit("yolo_detection", {
                "label":        "unrecognized",
                "confidence":   result["confidence"],
                "display":      f"Low confidence ({result['total_frames']} frames)",
                "breakdown":    result["breakdown"],
                "total_frames": result["total_frames"],
            })
            return

        category   = result["winner"]
        confidence = result["confidence"]

        # Servo overlay: shown until Arduino confirms close (10 s safety cap)
        self._set_active_servo(category, time.time() + 10.0)

        self._serial_send(f"LABEL:{category}")

        self._emit("servo_update",   {"type": category, "active": True})
        self._emit("yolo_detection", {
            "label":        category,
            "confidence":   confidence,
            "display":      category.capitalize(),
            "breakdown":    result["breakdown"],
            "total_frames": result["total_frames"],
        })
        self._emit("buffer_update", {
            "collecting":   False,
            "committed":    True,
            "winner":       category,
            "confidence":   confidence,
            "total_frames": result["total_frames"],
            "min_frames":   self._min_frames,
            "gap_counter":  0,
            "gap_limit":    self._gap_limit,
            "breakdown":    result["breakdown"],
            "leader":       category,
        })

    def _emit_state(self):
        with self._lock:
            votes      = list(self._buf.votes)
            collecting = self._buf.collecting
            gap        = self._buf.gap_counter

        result = self._compute_result(votes) if votes else None
        self._emit("buffer_update", {
            "collecting":   collecting,
            "total_frames": len(votes),
            "min_frames":   self._min_frames,
            "gap_counter":  gap,
            "gap_limit":    self._gap_limit,
            "breakdown":    result["breakdown"] if result else {},
            "leader":       result["winner"]    if result else None,
        })

    def _compute_result(self, votes: list[tuple[str, float]]) -> dict | None:
        if not votes:
            return None

        c            = Counter()
        total_weight = 0.0
        for cat, w in votes:
            c[cat]       += w
            total_weight += w

        winner, top_weight = c.most_common(1)[0]
        breakdown = {
            cat: {"count": n, "pct": round(n / total_weight * 100)}
            for cat, n in c.most_common()
        }
        return {
            "winner":         winner,
            "confidence":     round(top_weight / total_weight, 3),
            "total_frames":   len(votes),
            "breakdown":      breakdown,
            "low_confidence": len(votes) < self._min_frames,
        }

    # ── Read-only accessors (for the inference loop overlay) ──────────────────

    @property
    def collecting(self) -> bool:
        with self._lock:
            return self._buf.collecting

    @property
    def gap_counter(self) -> int:
        with self._lock:
            return self._buf.gap_counter

    def snapshot(self) -> tuple[bool, list[str], int]:
        """Returns (collecting, vote_categories, gap_counter) for the CV overlay."""
        with self._lock:
            return (
                self._buf.collecting,
                self._buf.snapshot_votes(),
                self._buf.gap_counter,
            )