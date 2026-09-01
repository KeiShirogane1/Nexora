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
    finally:
        conn.close()
