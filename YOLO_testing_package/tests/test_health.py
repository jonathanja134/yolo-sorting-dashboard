import time

from core.health import HealthMonitor

def test_health_monitor_is_alive_after_creation():
    h = HealthMonitor()
    assert h.is_alive()
    assert h.errors == 0


def test_health_monitor_records_errors():
    h = HealthMonitor()
    h.error()
    h.error()
    assert h.errors == 2


def test_health_monitor_frame_ok_resets_timer(monkeypatch):
    import core.health as health_module

    current = 1_000_000.0
    monkeypatch.setattr(health_module.time, "time", lambda: current)
    h = HealthMonitor()
    assert h.is_alive()

    monkeypatch.setattr(health_module.time, "time", lambda: current + 3)
    assert not h.is_alive()

    h.frame_ok()
    monkeypatch.setattr(health_module.time, "time", lambda: current + 4)
    assert h.is_alive()
