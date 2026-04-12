from core.health import HealthMonitor

def test_health_monitor():
    h = HealthMonitor()
    assert h.is_alive()

    h.error()
    assert h.errors == 1
