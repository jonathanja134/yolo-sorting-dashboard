"""
Buffer.py – Always-on majority-vote detection buffer.

Collection never stops. Commits are triggered ONLY by:
  1. SENSOR:1:TRIGGERED (pin 12) → commit if >= min_frames, wipe, keep going
  2. Manual clear (keyboard 'C') → commit whatever was gathered, wipe, reset
  3. gap_limit consecutive empty frames → commit if >= min_frames, wipe (fallback)

Rule: Only one database entry per sensor trigger. The add() method never
auto-commits; it just accumulates frames for better accuracy. Commits only
happen when explicitly triggered (sensor or manual clear).

There is no collecting gate. add() and no_detection() are always live.

Usage in yolo_reader.py:
    from ProgramManager.Buffer import BufferManager

    buffer_mgr = BufferManager(
        min_frames       = args.min_frames,
        gap_limit        = args.gap_limit,
        emit_fn          = _async_emit,
        serial_send_fn   = serial.send,
        get_active_servo = lambda: (active_servo, active_servo_until),
        set_active_servo = lambda cat, t: ...,
    )

    # In the inference loop:
    buffer_mgr.add(category, weight=confidence)
    buffer_mgr.no_detection()

    # On SENSOR:1:TRIGGERED (pin 12):
    buffer_mgr.handle_pin12()
"""

import threading
import time
from collections import Counter

_buf_mgr = None


def configure_buffer_manager(buffer_manager):
    global _buf_mgr
    _buf_mgr = buffer_manager

class DetectionBuffer:
    """
    Low-level vote accumulator. No collecting flag — always active.
    All methods must be called with the caller holding buf_lock.
    """

    def __init__(self):
        self.votes: list[tuple[str, float]] = []
        self.gap_counter: int = 0

    def reset(self):
        """Wipe votes and gap counter. Collection continues immediately."""
        self.votes       = []
        self.gap_counter = 0

    def add(self, category: str, weight: float = 1.0):
        self.votes.append((category, weight))
        self.gap_counter = 0

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
    High-level manager wrapping DetectionBuffer.

    Commit triggers (ONLY these cause database entries):
      - handle_pin12() : fires on SENSOR:1:TRIGGERED if frame_count >= min_frames
      - handle_clear() : fires on manual clear (keyboard 'C'), commits whatever gathered
      - no_detection() : fires when gap_counter reaches gap_limit (fallback if no sensor)

    The add() method only accumulates frames, it never auto-commits. This ensures
    exactly one database entry per sensor trigger event, eliminating duplicates when
    the same object remains in view for multiple frames after triggering.

    After every commit the buffer is wiped atomically (under lock, before the
    commit thread starts) so new detections never race into a stale window.

    The _pin12_just_committed flag prevents the gap_limit fallback from re-committing
    after a sensor trigger has already sent the data to the database.
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

        # Rule 4: set True after a pin12 commit; cleared when the gap signals
        # the object has left so the next pin12 event is treated as new.
        self._pin12_just_committed = False

    # ── Public API (called from yolo_reader.py) ────────────────────────────────

    def add(self, category: str, weight: float = 1.0):
        """
        Record a detection for this frame.
        No auto-commit. Only sensor trigger (handle_pin12) or manual clear 
        (handle_clear) can commit. This ensures one database entry per sensor trigger.
        """
        with self._lock:
            self._buf.add(category, weight)

        self._emit_state()

    def no_detection(self):
        """
        Record that this frame had no detection above threshold.

        Normal behaviour: commits if gap_limit is reached and votes exist.
        Post-pin12 behaviour (rule 4): if _pin12_just_committed is set, the
        gap signals the object has left — clear the flag and wipe without
        committing, so the next arrival starts a fresh event.
        """
        snapshot = None
        with self._lock:
            self._buf.gap_counter += 1
            gap = self._buf.gap_counter

            if gap >= self._gap_limit and self._buf.frame_count > 0:
                if self._pin12_just_committed:
                    # Object from the last pin12 event has now left — reset
                    # without committing (already counted once, rule 4).
                    print("[BUFFER] gap after pin12 commit — wiping without re-commit (rule 4)")
                    self._buf.reset()
                    self._pin12_just_committed = False
                else:
                    snapshot = list(self._buf.votes)
                    self._buf.reset()

        self._emit_state()

        if snapshot is not None:
            print(f"[BUFFER] gap limit reached -> auto-commit ({len(snapshot)} frames)")
            self._trigger_commit(snapshot)

    def handle_pin12(self):
        """
        Called on SENSOR:1:TRIGGERED (pin 12).
        Commits if >= min_frames accumulated, then wipes and keeps going.
        If below min_frames the buffer is still wiped (not enough data).
        Sets _pin12_just_committed = True after a successful commit to prevent
        the gap_limit fallback from re-committing the same object.
        """
        snapshot   = None
        has_enough = False

        with self._lock:
            has_enough = self._buf.frame_count >= self._min_frames
            if has_enough:
                snapshot = list(self._buf.votes)
                self._pin12_just_committed = True   # rule 4: suppress further commits
            self._buf.reset()

        if has_enough:
            print(f"[BUFFER] pin12 → committing ({len(snapshot)} frames)")
            self._trigger_commit(snapshot)
        else:
            print(f"[BUFFER] pin12 → wiped "
                  f"({self._buf.frame_count}/{self._min_frames} frames, below threshold)")

        self._emit_state()

    # ── handle_clear / handle_reset (keyboard 'C') ────────────────────────────

    def handle_reset(self):
        """Alias for handle_clear -> called by KeyboardSimulation.py."""
        self.handle_clear()

    def handle_clear(self):
        """
        Called on keyboard 'C'.
        Commits whatever was gathered (regardless of min_frames), then wipes.
        Also resets the pin12 guard so a manual clear fully resets state.
        """
        snapshot = None
        with self._lock:
            if self._buf.frame_count > 0:
                snapshot = list(self._buf.votes)
                self._buf.reset()
            self._pin12_just_committed = False

        if snapshot:
            self._trigger_commit(snapshot)
        self._emit_state()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _trigger_commit(self, votes: list[tuple[str, float]]):
        threading.Thread(target=self._commit, args=(votes,), daemon=True).start()

    def _commit(self, votes: list[tuple[str, float]]):
        result = self._compute_result(votes)

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

        self._emit("yolo_detection", {
            "label":        category,
            "confidence":   confidence,
            "display":      category.capitalize(),
            "breakdown":    result["breakdown"],
            "total_frames": result["total_frames"],
        })
        self._emit("buffer_update", {
            "collecting":   True,   # always collecting
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
            votes = list(self._buf.votes)
            gap   = self._buf.gap_counter

        result = self._compute_result(votes) if votes else None
        self._emit("buffer_update", {
            "collecting":   True,  
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
        return True 

    @property
    def gap_counter(self) -> int:
        with self._lock:
            return self._buf.gap_counter

    def snapshot(self) -> tuple[bool, list[str], int]:
        """Returns (collecting, vote_categories, gap_counter) for the CV overlay."""
        with self._lock:
            return (
                True,
                self._buf.snapshot_votes(),
                self._buf.gap_counter,
            )