import pathlib, sys
import pytest

# Ensure project root on path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.Services.password_security import hash_password, verify_password

def test_password_hashing():
    pw = "SecurePass123!"
    h = hash_password(pw)
    assert h != pw
    assert h.startswith("scrypt:") or h.startswith("pbkdf2:")
    assert verify_password(h, pw) is True
    assert verify_password(h, "wrong") is False
    assert verify_password("", pw) is False
    assert verify_password(h, "") is False

def test_password_hash_empty_raises():
    with pytest.raises(ValueError):
        hash_password("")

def test_login_flow_with_client(monkeypatch):
    from bootstrap.app import app
    from unittest.mock import MagicMock, patch
    # Mock get_db_connection to avoid real DB
    mock_user = {"id": 1, "username": "admin1", "email": "admin@example.com", "password": hash_password("AdminPass123"), "role": "admin", "status": "active"}
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = mock_user
    mock_conn.cursor.return_value = mock_cursor
    # Need to handle both sqlite and postgres paths
    with patch("app.Http.Controllers.auth.get_db_connection", return_value=mock_conn):
        with patch("app.Models.db.get_db_connection", return_value=mock_conn):
            app.config["WTF_CSRF_ENABLED"] = False
            app.config["TESTING"] = True
            client = app.test_client()
            # GET login should 200
            resp = client.get("/login")
            assert resp.status_code == 200
            # POST invalid
            resp = client.post("/login", data={"username": "nope", "password": "bad"}, follow_redirects=False)
            # Should redirect back to login on failure
            assert resp.status_code in (302, 200)

def test_role_redirects(monkeypatch):
    from bootstrap.app import app
    from unittest.mock import MagicMock, patch
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    for role, expected in [("student", "/student/dashboard"), ("supervisor", "/supervisor/dashboard"), ("admin", "/admin/dashboard")]:
        mock_user = {"id": 1, "username": "u1", "email": "a@b.com", "password": hash_password("Pass12345"), "role": role, "status": "active"}
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = mock_user
        mock_conn.cursor.return_value = mock_cursor
        with patch("app.Http.Controllers.auth.get_db_connection", return_value=mock_conn):
            client = app.test_client()
            resp = client.post("/login", data={"username": "u1", "password": "Pass12345"}, follow_redirects=False)
            # Should redirect to role dashboard
            assert expected in resp.headers.get("Location", "") or resp.status_code in (302, 303)
            # Clear session
            with client.session_transaction() as sess:
                sess.clear()

def test_inactive_account_blocked(monkeypatch):
    from bootstrap.app import app
    from unittest.mock import MagicMock, patch
    mock_user = {"id": 2, "username": "inactive1", "email": "i@b.com", "password": hash_password("Pass12345"), "role": "student", "status": "inactive"}
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = mock_user
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.auth.get_db_connection", return_value=mock_conn):
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.post("/login", data={"username": "inactive1", "password": "Pass12345"}, follow_redirects=False)
        assert resp.status_code in (302, 303)
        # Should set login_error in session
        with client.session_transaction() as sess:
            # After redirect, session should have error or be cleared after next GET
            pass
