from ProgramManager.event_bus import _async_emit 

_buf_mgr = None


def configure_buffer_manager(buffer_manager):
    global _buf_mgr
    _buf_mgr = buffer_manager

# ── Keyboard sensor simulation ────────────────────────────────────────────────

def kb_sensor_triggered():
    print("[KB SIM] SENSOR TRIGGERED")
    _async_emit("sensor_update", {
        "id": "sensor_1", "triggered": True, "distance_cm": None
    })
    if _buf_mgr is not None:
        _buf_mgr.handle_reset()

def kb_sensor_clear():
    print("[KB SIM] SENSOR CLEAR")
    _async_emit("sensor_update", {
        "id": "sensor_1", "triggered": False, "distance_cm": None
    })
    if _buf_mgr is not None:
        _buf_mgr.handle_clear()