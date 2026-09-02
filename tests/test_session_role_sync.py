import pathlib
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from flask import Flask, session

from app.Http.Middleware.security import login_required, role_required


class FakeRow:
    def __init__(self, role, status):
        self.values = (role, status)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.values[key]
        return {"role": self.values[0], "status": self.values[1]}[key]

    def __len__(self):
        return len(self.values)


def _app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    return app


def _db_row(role, status="active"):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = FakeRow(role, status)
    return conn


def test_role_required_repairs_stale_session_role_and_redirects():
    app = _app()

    @app.get("/student/dashboard")
    @role_required("student")
    def student_dashboard():
        return "student"

    client = app.test_client()
    with patch("app.Http.Middleware.security.get_db_connection", return_value=_db_row("supervisor")):
        with client.session_transaction() as sess:
            sess["user_id"] = 123
            sess["role"] = "student"

        response = client.get("/student/dashboard", follow_redirects=False)

    assert response.status_code in (302, 303)
    assert response.headers["Location"].endswith("/supervisor/dashboard")
    with client.session_transaction() as sess:
        assert sess["role"] == "supervisor"


def test_login_required_also_refreshes_stale_role():
    app = _app()

    @app.get("/change-password")
    @login_required
    def change_password():
        return session["role"]

    client = app.test_client()
    with patch("app.Http.Middleware.security.get_db_connection", return_value=_db_row("student")):
        with client.session_transaction() as sess:
            sess["user_id"] = 456
            sess["role"] = "supervisor"

        response = client.get("/change-password")

    assert response.status_code == 200
    assert response.data == b"student"
    with client.session_transaction() as sess:
        assert sess["role"] == "student"


def test_invalid_or_deleted_user_clears_session():
    app = _app()

    @app.get("/student/dashboard")
    @role_required("student")
    def student_dashboard():
        return "student"

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    client = app.test_client()

    with patch("app.Http.Middleware.security.get_db_connection", return_value=conn):
        with client.session_transaction() as sess:
            sess["user_id"] = 789
            sess["role"] = "student"

        response = client.get("/student/dashboard", follow_redirects=False)

    assert response.status_code in (302, 303)
    assert response.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "role" not in sess


def test_inactive_user_is_blocked_and_session_cleared():
    app = _app()

    @app.get("/student/dashboard")
    @role_required("student")
    def student_dashboard():
        return "student"

    client = app.test_client()
    with patch("app.Http.Middleware.security.get_db_connection", return_value=_db_row("student", "inactive")):
        with client.session_transaction() as sess:
            sess["user_id"] = 999
            sess["role"] = "student"

        response = client.get("/student/dashboard")

    assert response.status_code == 403
    assert b"Account deactivated" in response.data
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "role" not in sess
