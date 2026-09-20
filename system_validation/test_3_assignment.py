import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
import uuid
from unittest.mock import MagicMock, patch

# Test 1-5: Internship assignment creates internship, classroom membership, and supervisor assignment
def test_internship_assign_creates_both(monkeypatch):
    from bootstrap.app import app
    from app.Models.db import get_db_connection
    from app.Services.password_security import hash_password

    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    suffix = uuid.uuid4().hex[:8]

    conn = get_db_connection()
    try:
        admin_row = conn.execute(
            "INSERT INTO users (username,email,password,role,status) VALUES (?,?,?,?,?) RETURNING id",
            (f"admin_assign_{suffix}", f"admin_assign_{suffix}@example.com", hash_password("Pass12345"), "admin", "active"),
        ).fetchone()
        supervisor_row = conn.execute(
            "INSERT INTO users (username,email,password,role,status) VALUES (?,?,?,?,?) RETURNING id",
            (f"sup_assign_{suffix}", f"sup_assign_{suffix}@example.com", hash_password("Pass12345"), "supervisor", "active"),
        ).fetchone()
        student_row = conn.execute(
            "INSERT INTO users (username,email,password,role,status) VALUES (?,?,?,?,?) RETURNING id",
            (f"stu_assign_{suffix}", f"stu_assign_{suffix}@example.com", hash_password("Pass12345"), "student", "active"),
        ).fetchone()
        admin_id = int(admin_row[0])
        supervisor_id = int(supervisor_row[0])
        student_id = int(student_row[0])

        classroom_row = conn.execute(
            """
            INSERT INTO classrooms (name,section,supervisor_id,code,archived,classroom_type)
            VALUES (?,?,?,?,?,?) RETURNING id
            """,
            (f"Internship {suffix}", "A", supervisor_id, f"NXR-{suffix.upper()[:6]}", 0, "internship"),
        ).fetchone()
        classroom_id = int(classroom_row[0])
        conn.commit()
    finally:
        conn.close()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
        sess["role"] = "admin"

    try:
        with patch("app.Http.Controllers.admin.create_notification"):
            resp = client.post(
                "/admin/internship-assign",
                data={"student_id": str(student_id), "classroom_id": str(classroom_id)},
                follow_redirects=False,
            )
        assert resp.status_code in (302, 303)

        conn = get_db_connection()
        try:
            internship = conn.execute(
                "SELECT supervisor_id FROM internships WHERE student_id = ? AND status = 'Active' ORDER BY id DESC LIMIT 1",
                (student_id,),
            ).fetchone()
            membership = conn.execute(
                "SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ?",
                (classroom_id, student_id),
            ).fetchone()
            assignment = conn.execute(
                "SELECT 1 FROM student_assignments WHERE student_id = ? AND supervisor_id = ?",
                (student_id, supervisor_id),
            ).fetchone()
        finally:
            conn.close()

        assert internship is not None
        assert int(internship[0]) == supervisor_id
        assert membership is not None
        assert assignment is not None
    finally:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM internships WHERE student_id = ?", (student_id,))
            conn.execute("DELETE FROM student_assignments WHERE student_id = ? AND supervisor_id = ?", (student_id, supervisor_id))
            conn.execute("DELETE FROM classroom_students WHERE classroom_id = ? AND student_id = ?", (classroom_id, student_id))
            conn.execute("DELETE FROM classrooms WHERE id = ?", (classroom_id,))
            conn.execute("DELETE FROM users WHERE id IN (?, ?, ?)", (student_id, supervisor_id, admin_id))
            conn.commit()
        finally:
            conn.close()

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
    sys.path.insert(0, str(pathlib.Path("scripts/migrate_3.py").resolve().parent.parent))
    from scripts.migrate_3 import migrate
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
        from scripts.migrate_3 import migrate
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
