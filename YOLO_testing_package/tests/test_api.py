import pytest
from Dashboard.app import app 

# ─────────────────────────────────────────────
# Flask test client fixture
# ─────────────────────────────────────────────
@pytest.fixture
def test_state_endpoint(client):
    response = client.get("/api/state")

    assert response.status_code == 200

    data = response.get_json()

    # basic structure checks
    assert "conveyors" in data
    assert "counts" in data
    assert "recent_events" in data

    # deeper checks
    assert isinstance(data["conveyors"], list)
    assert isinstance(data["counts"], dict)