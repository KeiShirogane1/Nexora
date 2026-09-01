import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bootstrap.app import app
from app.Models.db import get_db_connection


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


@pytest.fixture
def db():
    conn = get_db_connection()
    try:
        yield conn
        # Ensure any uncommitted transaction is rolled back for isolation.
        # Committed test data persists, so tests must use unique data (uuid).
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
