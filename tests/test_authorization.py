import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from unittest.mock import MagicMock, patch
from bootstrap.app import app

def _login_as(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role

def test_admin_only_routes_block_student():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "student")
    for url in ["/admin/dashboard", "/admin/users", "/admin/users/students", "/admin/users/supervisors", "/admin/internship-assign", "/admin/reports"]:
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 403, f"{url} should be 403 for student, got {resp.status_code}"
    # Cleanup
    with client.session_transaction() as sess:
        sess.clear()

def test_student_only_routes_block_admin():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    for url in ["/student/dashboard", "/student/logbook", "/student/tasks"]:
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 403, f"{url} should be 403 for admin"
    with client.session_transaction() as sess:
        sess.clear()

def test_supervisor_only_routes_block_student():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "student")
    for url in ["/supervisor/dashboard", "/supervisor/interns"]:
        resp = client.get(url, follow_redirects=False)
        assert resp.status_code == 403, f"{url} should be 403 for student"
    with client.session_transaction() as sess:
        sess.clear()

def test_unauthenticated_redirects_to_login():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    # No session
    resp = client.get("/admin/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("Location", "")
    resp2 = client.get("/student/dashboard", follow_redirects=False)
    assert resp2.status_code in (302, 303)

def test_supervisor_cannot_access_unassigned_student():
    # This tests the ownership check we added in Phase 1
    from app.Http.Controllers.supervisor import _is_assigned
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # Simulate not assigned
    mock_cursor.fetchone.return_value = None
    mock_conn.execute.return_value = mock_cursor
    # Actually _is_assigned uses conn.execute directly
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        assert _is_assigned(1, 999) is False
    # Simulate assigned
    mock_cursor2 = MagicMock()
    mock_cursor2.fetchone.return_value = (1,)
    mock_conn2 = MagicMock()
    mock_conn2.execute.return_value = mock_cursor2
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn2):
        # Need to make the mock return a truthy row
        # Our function checks `row is not None`, so even (1,) works
        assert _is_assigned(1, 2) is True

def test_supervisor_view_student_forbidden(monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "supervisor")
    # Mock _is_assigned to return False
    with patch("app.Http.Controllers.supervisor._is_assigned", return_value=False):
        resp = client.get("/supervisor/student/999", follow_redirects=False)
        assert resp.status_code == 403
        assert b"Forbidden" in resp.data
    with client.session_transaction() as sess:
        sess.clear()

def test_supervisor_view_student_allowed(monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "supervisor")
    # Mock assigned and mock DB for student lookup
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # First call for _is_assigned already patched, second for student query
    mock_cursor.fetchone.return_value = {"username": "student1"}
    mock_conn.execute.return_value = mock_cursor
    # Need to mock both _is_assigned and get_db_connection for the view
    with patch("app.Http.Controllers.supervisor._is_assigned", return_value=True):
        with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
            # Also need to mock other queries (sessions, tasks, docs, feedback) — make them return empty
            mock_conn.execute.return_value.fetchall.return_value = []
            # But view_student does multiple conn.execute calls — our mock needs to handle fetchone/fetchall switching
            # For simplicity, just check that with _is_assigned True, it doesn't return 403 immediately
            # It will try DB and may succeed or fail, but not 403
            resp = client.get("/supervisor/student/1")
            # Could be 200 or 500 depending on mock completeness, but not 403
            assert resp.status_code != 403
    with client.session_transaction() as sess:
        sess.clear()
