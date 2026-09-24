import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must be set before app.py is imported: it reads the secret once at import.
os.environ["APPHUB_PROXY_SECRET"] = "test-secret"
ADMIN_HEADERS = {"X-Apphub-Auth": "test-secret"}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets its own empty library.db."""
    import database.databaseConnector as databaseConnector
    import database.suggestionsRepo as suggestionsRepo
    monkeypatch.setattr(databaseConnector, "DB_PATH", tmp_path / "library.db")
    databaseConnector.init_db()
    suggestionsRepo.invalidate_library_index()
    yield


@pytest.fixture
def client():
    import app as app_module
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def friend():
    import database.suggestionsRepo as suggestionsRepo
    return suggestionsRepo.create_friend("Test Friend")
