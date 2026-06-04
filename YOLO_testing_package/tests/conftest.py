import sys
from pathlib import Path

# Ensure the workspace root is importable for Dashboard/ProgramManager modules.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest
from Dashboard.app import app


@pytest.fixture
def client():
    return app.test_client()
