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
_TEST_IDENTITY_PREFIX = "__nexora_pytest_identity_"

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


def _row_value(row, key, index):
    try:
        return row[key]
    except Exception:
        return row[index]


def _ensure_manual_test_identity(sess):
    user_id = sess.get("user_id")
    role = sess.get("role")
    if not user_id or role not in {"student", "supervisor", "admin"}:
        return None

    synthetic_username = f"{_TEST_IDENTITY_PREFIX}{user_id}"
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, username, role, status, session_version FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            conn.execute(
                """
                INSERT INTO users (id, username, password, role, status)
                VALUES (?, ?, ?, ?, 'active')
                """,
                (
                    user_id,
                    synthetic_username,
                    "pytest-only-not-for-login",
                    role,
                ),
            )
        elif _row_value(row, "username", 1) == synthetic_username:
            # Old tests reuse a few fixed IDs under different roles. Only rows
            # created by this harness may be repaired; genuine fixture users
            # are never rewritten.
            conn.execute(
                "UPDATE users SET role = ?, status = 'active' WHERE id = ?",
                (role, user_id),
            )

        conn.commit()
        return conn.execute(
            "SELECT id, username, role, status, session_version FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


class NexoraTestClient(FlaskClient):
    @contextmanager
    def session_transaction(self, *args, **kwargs):
        with super().session_transaction(*args, **kwargs) as sess:
            yield sess

            row = _ensure_manual_test_identity(sess)
            if (
                sess.get("role") != "supervisor"
                or not sess.get("user_id")
                or "session_version" in sess
                or row is None
            ):
                return

            version = _row_value(row, "session_version", 4)
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
