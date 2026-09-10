import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from unittest.mock import MagicMock, patch
from bootstrap.app import app

def _login_as(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role

def test_bulk_activate_works():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # Mock user lookups
    def side_effect(sql, params=None):
        if "SELECT role, status FROM users WHERE id = ?" in sql:
            # Return pending_student for id 2, student for id 3
            if params[0] == 2:
                mock_cursor.fetchone.return_value = {"role": "pending_student", "status": "active"}
            elif params[0] == 3:
                mock_cursor.fetchone.return_value = {"role": "student", "status": "inactive"}
            else:
                mock_cursor.fetchone.return_value = None
        elif "UPDATE users SET" in sql:
            mock_cursor.rowcount = 1
        return mock_cursor
    # Actually bulk uses SELECT role, status FROM users WHERE id = ?
    mock_cursor.execute.side_effect = lambda sql, params=None: (setattr(mock_cursor, 'rowcount', 1) or mock_cursor) if "UPDATE" in sql else mock_cursor
    # Simpler: mock fetchone for each id
    mock_cursor.fetchone.side_effect = [
        {"role": "pending_student", "status": "active"},
        {"role": "student", "status": "inactive"},
    ]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.commit = MagicMock()
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids": [2,3], "action": "activate"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["updated_count"] >= 1

def test_bulk_deactivate_works():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"role": "student", "status": "active"}
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids": [2], "action": "deactivate"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

def test_bulk_delete_soft():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # For delete, pending -> rejected, active -> inactive
    mock_cursor.fetchone.side_effect = [
        {"role": "pending_student", "status": "active"},
        {"role": "student", "status": "active"},
    ]
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids": [2,3], "action": "delete"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

def test_bulk_requires_admin():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 2, "student")
    resp = client.post("/admin/users/bulk", json={"ids": [3], "action": "activate"})
    assert resp.status_code == 403

def test_bulk_requires_csrf():
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    resp = client.post("/admin/users/bulk", json={"ids": [2], "action": "activate"})
    assert resp.status_code == 400

def test_bulk_rejects_invalid_action():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    resp = client.post("/admin/users/bulk", json={"ids": [2], "action": "invalid"})
    assert resp.status_code == 400

def test_bulk_rejects_admin_ids():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"role": "admin", "status": "active"}
    mock_cursor.rowcount = 0
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids": [1], "action": "deactivate"})
        data = resp.get_json()
        assert data["success"] is True
        assert data["updated_count"] == 0

def test_bulk_transaction_rollback_on_failure():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"role": "student", "status": "active"}
    # Make execute raise on second call
    def side_effect(sql, params=None):
        if "UPDATE" in sql and len(mock_cursor.execute.call_args_list) > 2:
            raise Exception("DB error")
        mock_cursor.rowcount = 1
        return mock_cursor
    mock_cursor.execute.side_effect = side_effect
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.rollback = MagicMock()
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids": [2,3], "action": "deactivate"})
        assert resp.status_code == 500
        assert mock_conn.rollback.called
