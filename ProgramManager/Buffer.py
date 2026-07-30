"""
Buffer.py – Uses the majority vote buffer to compile the best match for the detected device.

Commits are triggered by gap_limit consecutive empty frames 
    => commit if counted frame is above min_frames, then reset the buffer
"""

import threading,time 
from collections import Counter

_buf_mgr = None

# configure_buffer_manager change the function holder from none to buffer_manager for normal operation
def configure_buffer_manager(buffer_manager):
    global _buf_mgr
    _buf_mgr = buffer_manager

class DetectionBuffer:
    "Vote accumulator which is always active"
    def __init__(self):
        self.votes: list[tuple[str, float]] = []
        self.gap_counter: int = 0
    
    def reset(self):
        "Reset the votes and gap counter and then collection continues "
        self.votes       = []
        self.gap_counter = 0
    
    def add(self, category: str, weight: float = 1.0):
        "Process the finished detection window asynchronously."
        self.votes.append((category, weight))
        self.gap_counter = 0

    @property
    def frame_count(self) -> int:
        "Return the number of buffered frame"
        return len(self.votes)
    
    def snapshot_votes(self) -> list[str]:
        "Return a plain list of category names (no weights) to clean the data"
        return [v[0] for v in self.votes]

class BufferManager:
    """
    High-level manager that handle the wrapped data from DetectionBuffer.
    After every commit the buffer is reset automically so new detections never race into a stale window.
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

    # PUBLIC API called from yolo_detect_ncnn_headless.py 

    def add(self, category: str, weight: float = 1.0):
        "Record a detection for this frame with lock safe ensuring one function only edits the data"
        with self._lock:
            self._buf.add(category, weight)
        self._emit_state()

    def no_detection(self):
        "Record empty detection frames then commits if gap_limit is reached and votes exist."
        snapshot = None
        with self._lock:
            self._buf.gap_counter += 1
            gap = self._buf.gap_counter
            #if the gap is bove the gap limit and frame>0 therefore it saves the votes in snapshot 
            if gap >= self._gap_limit and self._buf.frame_count > 0:
                snapshot = list(self._buf.votes)
                self._buf.reset()
        self._emit_state()
        
        if snapshot is not None:
            #the saved snapshot gets commited if not null
            print(f"[BUFFER] gap limit reached -> commit ({len(snapshot)} frames)")
            self._trigger_commit(snapshot)

    # INTERNAL HELPERS

    def _trigger_commit(self, votes: list[tuple[str, float]]):
        "on ._trigger_commit(snapshot) a thread start to fire _comit and compute the votes without performance loss"
        threading.Thread(target=self._commit, args=(votes,), daemon=True).start()
    def _commit(self, votes: list[tuple[str, float]]):
        "thread sending the votes result to the yolo program "
        result = self._compute_result(votes)
        # if no result return 
        if result is None:
            print("[COMMIT] empty buffer — skipped")
            return

        print(f"[COMMIT] {result}")
        # in case of low confidence result data are still send for log but servo aren't triggered
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

        self._set_active_servo(category, time.time() + 10.0)#10 seconds timeout for safety cap

        #Send the category result thought the serial to the arduino for actuation using the serial protocal 
        self._serial_send(f"LABEL:{category}")
        # send detection to the dashboard for log 
        self._emit("yolo_detection", {
            "label":        category,
            "confidence":   confidence,
            "display":      category.capitalize(),
            "breakdown":    result["breakdown"],
            "total_frames": result["total_frames"],
        })
        # send live detection to the dahsbord 
        self._emit("buffer_update", {
            "collecting":   True,  
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
        "function that triggers the buffer update on each frames"
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
        "Compute the result of the votes called by _emit_state for live preview and _commit for final descision"
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

    #  Read-only accessors for the inference loop overlay


    def snapshot(self) -> tuple[bool, list[str], int]:
        "Returns (collecting, vote_categories, gap_counter) for the CV overlay."
        with self._lock:
            return (
                True,
                self._buf.snapshot_votes(),
                self._buf.gap_counter,
            )