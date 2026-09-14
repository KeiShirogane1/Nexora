import os
import pathlib
import sys
import tempfile
from contextlib import contextmanager

import pytest
from flask.testing import FlaskClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Tests must never use the developer SQLite database or a configured Render
# PostgreSQL database. Set explicit test-only environment values before
# importing bootstrap.app because bootstrap loads .env during import.
_TEST_DB_DIR = tempfile.TemporaryDirectory(prefix="nexora-pytest-")
_TEST_DB_PATH = pathlib.Path(_TEST_DB_DIR.name) / "nexora_test.db"

os.environ["DATABASE_URL"] = ""
os.environ["FLASK_ENV"] = "testing"
os.environ["NEXORA_ENV"] = "testing"
os.environ["SECRET_KEY"] = "nexora-pytest-only-secret-key"
os.environ["ADMIN_USERNAME"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["ADMIN_RECOVERY_ENABLED"] = "false"

from app.Models import db as db_module

db_module.SQLITE_PATH = _TEST_DB_PATH

from bootstrap.app import app
from app.Models.db import get_db_connection


class NexoraTestClient(FlaskClient):
    @contextmanager
    def session_transaction(self, *args, **kwargs):
        with super().session_transaction(*args, **kwargs) as sess:
            yield sess

            if (
                sess.get("role") != "supervisor"
                or not sess.get("user_id")
                or "session_version" in sess
            ):
                return

            conn = get_db_connection()
            try:
                row = conn.execute(
                    "SELECT session_version FROM users WHERE id = ?",
                    (sess["user_id"],),
                ).fetchone()
            finally:
                conn.close()

            if row is not None:
                try:
                    version = row["session_version"]
                except Exception:
                    version = row[0]
                sess["session_version"] = int(version or 0)


app.test_client_class = NexoraTestClient


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
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
