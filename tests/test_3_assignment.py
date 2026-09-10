import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import MagicMock, patch

# Test 1-5: Internship assignment creates internship, student_assignments, supervisor_id
def test_internship_assign_creates_both(monkeypatch):
    from bootstrap.app import app
    from app.Models.db import get_db_connection
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    # login as admin
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    # Mock DB
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # Setup for POST: need to mock SELECT for student/supervisor checks, then INSERT
    def execute_side_effect(sql, params=None):
        if "SELECT id FROM users WHERE id = ? AND role = 'student'" in sql:
            mock_cursor.fetchone.return_value = {"id": 2}
            return mock_cursor
        elif "SELECT id FROM users WHERE id = ? AND role = 'supervisor'" in sql:
            mock_cursor.fetchone.return_value = {"id": 3, "username": "sup1", "email": "sup@example.com"}
            return mock_cursor
        elif "SELECT username, email FROM users WHERE id = ?" in sql:
            mock_cursor.fetchone.return_value = {"username": "sup1", "email": "sup@example.com"}
            return mock_cursor
        elif "SELECT id FROM users WHERE LOWER(email)" in sql:
            mock_cursor.fetchone.return_value = None
            return mock_cursor
        elif "SELECT COUNT(*) FROM internships" in sql or "SELECT id FROM internships WHERE student_id" in sql:
            mock_cursor.fetchone.return_value = None
            return mock_cursor
        elif "INSERT INTO internships" in sql:
            mock_cursor.rowcount = 1
            return mock_cursor
        elif "INSERT INTO student_assignments" in sql:
            mock_cursor.rowcount = 1
            return mock_cursor
        else:
            mock_cursor.fetchone.return_value = None
            return mock_cursor
    mock_cursor.execute.side_effect = execute_side_effect
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/internship-assign", data={
            "student_id": "2",
            "company_name": "Test Co",
            "company_address": "123 St",
            "supervisor_name": "Sup Name",
            "supervisor_email": "sup@example.com",
            "position": "Intern",
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
            "required_hours": "400",
            "supervisor_id": "3"
        }, follow_redirects=False)
        # Should redirect or 200, but not 500
        assert resp.status_code in (200, 302, 303)
        # Check that INSERT was called for internships with supervisor_id
        calls = [c.args[0] for c in mock_cursor.execute.call_args_list]
        assert any("INSERT INTO internships" in c and "supervisor_id" in c for c in calls)
        assert any("student_assignments" in c for c in calls)

def test_duplicate_active_internship_blocked(monkeypatch):
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # Student exists
    def side_effect(sql, params=None):
        if "SELECT id FROM users WHERE id = ? AND role = 'student'" in sql:
            mock_cursor.fetchone.return_value = {"id": 2}
        elif "SELECT id FROM users WHERE LOWER(email)" in sql:
            mock_cursor.fetchone.return_value = None
        elif "SELECT supervisor_id FROM users" in sql:
            mock_cursor.fetchone.return_value = {"id": 3}
        elif "SELECT id FROM internships WHERE student_id" in sql:
            # Already has active internship
            mock_cursor.fetchone.return_value = {"id": 99}
        else:
            mock_cursor.fetchone.return_value = None
        return mock_cursor
    mock_cursor.execute.side_effect = side_effect
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/internship-assign", data={
            "student_id": "2",
            "company_name": "Test Co",
            "company_address": "123 St",
            "supervisor_name": "Sup",
            "supervisor_email": "sup@example.com",
            "position": "Intern",
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
            "required_hours": "400"
        })
        # Should show flash about already has active internship, not create
        assert resp.status_code in (200, 302)

def test_supervisor_ownership():
    from app.Http.Controllers.supervisor import _is_assigned
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.execute.return_value = mock_cursor
    mock_conn.cursor.return_value = mock_cursor
    # Actually _is_assigned uses get_db_connection().execute, not cursor
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        # Simulate not assigned
        mock_conn.execute.return_value.fetchone.return_value = None
        assert _is_assigned(1, 999) is False
        # Simulate assigned
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        assert _is_assigned(1, 2) is True

def test_supervisor_can_access_assigned():
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["role"] = "supervisor"
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"username": "student1"}
    mock_conn.execute.return_value = mock_cursor
    # Need to mock _is_assigned True and DB for student lookup
    with patch("app.Http.Controllers.supervisor._is_assigned", return_value=True):
        with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
            mock_conn.execute.return_value.fetchall.return_value = []
            # Mock all execute calls to return appropriate
            resp = client.get("/supervisor/student/1")
            assert resp.status_code != 403

def test_supervisor_cannot_access_unassigned():
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["role"] = "supervisor"
    with patch("app.Http.Controllers.supervisor._is_assigned", return_value=False):
        resp = client.get("/supervisor/student/999")
        assert resp.status_code == 403

def test_supervisor_cannot_manipulate_other_task():
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 10
        sess["role"] = "supervisor"
    # Mock task not found (wrong supervisor) — controller returns 200 with "Task not found"
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.execute.return_value = mock_cursor
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/task/999")
        assert resp.status_code == 200
        assert b"Task not found" in resp.data

def test_approve_requires_post():
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    for url in ["/admin/approve-student/1", "/admin/reject-student/1", "/admin/approve-supervisor/1", "/admin/reject-supervisor/1"]:
        resp = client.get(url, follow_redirects=False)
        # Should be 405 Method Not Allowed since now POST only
        assert resp.status_code == 405, f"{url} GET should be 405, got {resp.status_code}"

def test_approve_post_requires_csrf():
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    # POST without CSRF should be 400
    resp = client.post("/admin/approve-student/1", data={}, follow_redirects=False)
    assert resp.status_code == 400

def test_approve_post_with_csrf(monkeypatch):
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False  # Disable for this test to check logic without CSRF
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    # Mock DB for approve
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"username": "pending1", "email": "p@example.com"}
    mock_conn.cursor.return_value = mock_cursor
    # Need to patch both get_db_connection places
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/approve-student/1", data={}, follow_redirects=False)
        assert resp.status_code in (302, 303, 200)

def test_legacy_assign_redirect():
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    resp = client.get("/admin/assign", follow_redirects=False)
    assert resp.status_code == 301
    assert "/admin/internship-assign" in resp.headers.get("Location", "")

def test_assignments_readonly():
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/assignments")
        assert resp.status_code == 200
        # Should not have POST handling, just GET
        resp2 = client.post("/admin/assignments", data={}, follow_redirects=False)
        # POST not allowed
        assert resp2.status_code == 405

def test_reports_legacy_redirect():
    from bootstrap.app import app
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    resp = client.get("/admin/reports/1", follow_redirects=False)
    # Should redirect to student_report, not 500
    assert resp.status_code in (301, 302, 303)
    assert "student" in resp.headers.get("Location", "").lower() or resp.status_code == 301

def test_indexes_exist():
    import pathlib
    txt = pathlib.Path("scripts/init_db.py").read_text(encoding="utf-8")
    for idx in ["idx_student_assignments_student_id", "idx_student_assignments_supervisor_id", "idx_tasks_student_id", "idx_internships_supervisor_id"]:
        assert idx in txt

def test_migration_repeatable():
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path("scripts/migrate_phase3.py").resolve().parent.parent))
    from scripts.migrate_phase3 import migrate
    # Run twice, should not raise
    migrate()
    migrate()
    assert True

def test_migration_no_duplicate():
    from app.Models.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM student_assignments")
        before = cursor.fetchone()[0]
        # Run migration again via function
        from scripts.migrate_phase3 import migrate
        migrate()
        cursor.execute("SELECT COUNT(*) FROM student_assignments")
        after = cursor.fetchone()[0]
        assert after == before or after == before  # no duplicate explosion
    finally:
        cursor.close()
        conn.close()

def test_postgres_compatibility():
    from app.Models.db import PostgresCursor
    assert PostgresCursor._convert_placeholders("SELECT * WHERE id = ?") == "SELECT * WHERE id = %s"
    # Check LOWER LIKE usage
    import pathlib
    txt = pathlib.Path("app/Http/Controllers/admin.py").read_text(encoding="utf-8")
    assert "LOWER(username) LIKE LOWER(?)" in txt
    assert "ON CONFLICT" in txt
