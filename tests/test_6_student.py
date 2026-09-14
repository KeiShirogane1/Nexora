import pathlib, sys, os, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from unittest.mock import MagicMock, patch
from bootstrap.app import app

def _login_as(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role

# helper to make mock that returns active status for student before_request
def _active_conn(mock_conn=None):
    if mock_conn is None:
        mock_conn = MagicMock()
    # before_request uses conn.execute SELECT status
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
        elif "FROM student_profiles" in sql:
            # generic profile fetch
            m.fetchone.return_value = ("John","M","Doe",20,"S123","pic.jpg","09123","Addr","2nd","BSIT","EC","Parent","09123","ec@e.com","john@e.com")
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec_side
    return mock_conn

# 1 dashboard isolation
def test_dashboard_isolation_no_other_student():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 95110, "student")
    context = {
        "profile_ready": True,
        "profile": {"first_name":"John","last_name":"Doe","student_id":"S1","major_program":"BSIT","grade_year":"2nd"},
        "internship": None,
        "log_count": 0,
        "task_total": 0,
        "task_completed": 0,
        "document_count": 0,
        "attendance_count": 0,
        "recent_logs": [],
        "recent_tasks": [],
        "recent_documents": [],
        "recent_attendance": [],
        "dashboard_classrooms": [],
        "open_attendance": None,
        "logbook_review_status": {},
        "dashboard_performance": {},
        "dashboard_competencies": [],
    }
    with patch("app.Services.student_dashboard_service.get_student_dashboard_context", return_value=context) as get_context:
        resp = client.get("/student/dashboard")
        assert resp.status_code == 200
        get_context.assert_called_once_with(95110)

def test_dashboard_requires_login():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/student/dashboard", follow_redirects=False)
    assert resp.status_code in (302,303)
    assert "/login" in resp.headers.get("Location","")

# 2 emergency schema
def test_emergency_schema_exists():
    txt = pathlib.Path("scripts/init_db.py").read_text(encoding="utf-8")
    assert "emergency_name" in txt
    assert "emergency_relationship" in txt
    assert "emergency_phone" in txt
    assert "emergency_email" in txt
    # check CREATE TABLE contains them
    assert "CREATE TABLE IF NOT EXISTS student_profiles" in txt
    # ensure SQLite migration exists
    assert "ALTER TABLE student_profiles ADD COLUMN emergency_name" in txt

# 3 profile setup validation
def test_profile_setup_requires_validation():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    mock_conn.execute.side_effect = lambda sql, params=None: MagicMock(fetchone=lambda: {"status":"active"}, fetchall=lambda: []) if "SELECT status" in sql else MagicMock()
    # Use side_effect that returns active for before_request
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        # invalid input is re-rendered in place with validation feedback
        resp = client.post("/student/profile/setup", data={"first_name":"", "last_name":"Doe", "middle_name":"M", "age":"20", "student_id":"S123", "phone_number":"09123", "home_address":"Addr", "grade_year":"2nd", "major_program":"BSIT"}, follow_redirects=False)
        assert resp.status_code == 200
        updates = [str(c) for c in mock_cursor.execute.call_args_list if "UPDATE student_profiles" in str(c)]
        assert len(updates)==0

# 4 profile photo CSRF
def test_profile_photo_csrf_rejected():
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    resp = client.post("/student/profile/photo", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400

def test_profile_photo_csrf_via_fetch_header():
    # verify template now includes X-CSRFToken
    txt = pathlib.Path("resources/views/student/profile.html").read_text(encoding="utf-8")
    assert 'X-CSRFToken' in txt
    assert 'csrf_token' in txt

# 5 internship isolation
def test_internship_isolation():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    # Active Intern Classroom lookup must remain scoped to the session student.
    txt = pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")
    assert "WHERE cs.student_id = ?" in txt
    assert 'session["user_id"]' in txt

# 6 clock-in
def test_clock_in_success_and_post_required():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None  # no open session
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.post("/student/clock-in")
        assert resp.status_code in (302,303)
        # GET should be 405
        resp2 = client.get("/student/clock-in")
        assert resp2.status_code == 405

def test_duplicate_open_prevention():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (1,)  # existing open
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        else:
            m.fetchone.return_value = (1,)
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.post("/student/clock-in")
        assert resp.status_code in (302,303)
        # ensure no INSERT
        inserts = [str(c) for c in mock_cursor.execute.call_args_list if "INSERT INTO attendance" in str(c)]
        assert len(inserts)==0
    # also check index exists
    assert "idx_attendance_open" in pathlib.Path("scripts/init_db.py").read_text(encoding="utf-8")

def test_clock_out_rollup():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # Current attendance row includes classroom_id as the third value.
    mock_cursor.fetchone.side_effect = [(1, "2026-01-01T08:00:00", None), (10,), (0,)]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT id" in sql and "attendance" in sql:
            m.fetchone.return_value = (1, "2026-01-01T08:00:00", None)
        else:
            m.fetchone.return_value = (5,)
        return m
    mock_conn.execute.side_effect = exec_side
    mock_cursor.fetchone.return_value = (1, "2026-01-01T08:00:00", None)
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.post("/student/clock-out")
        assert resp.status_code in (302,303)
        txt = pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")
        assert "UPDATE internships SET completed_hours" in txt

# 7 add log ownership
def test_add_log_requires_open_session():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None # no open
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.post("/student/log/add", data={"content":"hello"})
        assert resp.status_code in (302,303)
        inserts = [str(c) for c in mock_cursor.execute.call_args_list if "INSERT INTO logs" in str(c)]
        assert len(inserts)==0

def test_edit_log_ownership():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "FROM logs" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.get("/student/log/999/edit")
        assert resp.status_code == 404
        txt = pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")
        assert "UPDATE logs" in txt and "student_id" in txt

def test_delete_log_post_only():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.get("/student/log/1/delete")
        assert resp.status_code == 405

# 8 task ownership and IDOR
def test_task_upload_idor_blocked():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None # task not owned
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    # Also need cursor fetch for task ownership
    mock_cursor.fetchone.return_value = None
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        import io
        data = {"file": (io.BytesIO(b"hello"), "test.pdf")}
        resp = client.post("/student/task/999/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 404

def test_task_details_isolation():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "FROM tasks" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.get("/student/task/999")
        assert resp.status_code == 404

def test_submit_task_requires_submission_and_lifecycle():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    txt = pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")
    assert "requires_submission" in txt
    assert "create_notification" in txt
    assert "Pending" in txt and "Reopened" in txt

def test_submission_delete_post_only_and_csrf():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.get("/student/task/submission/1/delete")
        assert resp.status_code == 405
    # check template now POST
    tpl = pathlib.Path("resources/views/student/task_details.html").read_text(encoding="utf-8")
    assert 'action="/student/task/submission/{{ upload[0] }}/delete"' in tpl
    assert 'method="POST"' in tpl or 'method=\"POST\"' in tpl or 'csrf_token' in tpl
    # ensure safe_path
    assert "_is_safe_path" in pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")

def test_view_submission_authorization_and_safe_path():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "FROM task_submissions" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.get("/student/task/submission/999")
        assert resp.status_code == 404
    assert "_is_safe_path" in pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")
    assert "download_name" in pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")

# 9 documents
def test_document_upload_and_view():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def cursor_exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "COUNT(*)" in sql:
            m.fetchone.return_value = (0,)
            m.fetchall.return_value = []
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        return m
    mock_cursor.execute.side_effect = cursor_exec_side
    mock_cursor.fetchone.return_value = (0,)
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        import io
        data = {"file": (io.BytesIO(b"hello world"), "doc.pdf")}
        resp = client.post("/student/documents", data=data, content_type="multipart/form-data")
        assert resp.status_code in (200,302,303)

def test_document_view_isolation_and_traversal():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "FROM documents" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.get("/student/document/999")
        assert resp.status_code == 404
    tpl = pathlib.Path("resources/views/student/documents.html").read_text(encoding="utf-8")
    assert "csrf_token" in tpl
    assert "_is_safe_path" in pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")

# 10 notification CSRF
def test_notification_bell_csrf_header():
    txt = pathlib.Path("resources/views/components/role_notification_bell.html").read_text(encoding="utf-8")
    assert 'X-CSRFToken' in txt
    assert 'csrf_token' in txt
    wrapper = pathlib.Path("resources/views/components/student_notification_bell.html").read_text(encoding="utf-8")
    assert "role_notification_bell.html" in wrapper

# 11 inactive student blocked
def test_inactive_student_blocked():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_active = MagicMock()
    mock_active.fetchone.return_value = {"status":"inactive"}
    mock_conn.execute.return_value = mock_active
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.get("/student/dashboard")
        assert resp.status_code == 403
        assert b"deactivated" in resp.data.lower()

# 12 postgres compatibility
def test_postgres_uses_question_marks():
    txt = pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")
    assert "?" in txt
    assert "using_postgres" in pathlib.Path("app/Models/db.py").read_text(encoding="utf-8")
    # ensure no %s in student sql
    import re
    for line in txt.split("\n"):
        if "SELECT" in line or "INSERT" in line or "UPDATE" in line:
            # allow %s only in string formatting not sql
            if "%s" in line and "?" not in line:
                assert False, f"Found %s in {line}"

# 13 GET mutation rejection
def test_get_mutation_rejected():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        for path in ["/student/clock-in", "/student/clock-out", "/student/log/add", "/student/task/1/submit", "/student/task/submission/1/delete"]:
            resp = client.get(path)
            assert resp.status_code == 405, f"{path} GET should be 405 not {resp.status_code}"

# 14 sidebar dedup
def test_sidebar_dead_links_removed():
    txt = pathlib.Path("resources/views/components/student_sidebar.html").read_text(encoding="utf-8")
    # Progress and Attendance duplicates should be removed
    assert txt.count('>Progress<') == 0
    assert txt.count('>Attendance<') == 0
    # Should still have Dashboard, Logbook, Tasks, Documents, Logout
    assert "Dashboard" in txt
    assert "Logbook" in txt
    assert "Tasks" in txt
    assert "Documents" in txt

# 15 indexes
def test_student_indexes_exist():
    txt = pathlib.Path("scripts/init_db.py").read_text(encoding="utf-8")
    assert "idx_attendance_student_status" in txt
    assert "idx_logs_attendance_id" in txt
    assert "idx_task_submissions_task_id" in txt
    assert "idx_documents_student_id" in txt
    assert "idx_attendance_open" in txt

# 16 edit_log predicate
def test_edit_log_update_has_student_id():
    txt = pathlib.Path("app/Http/Controllers/student.py").read_text(encoding="utf-8")
    assert "UPDATE logs" in txt
    assert "WHERE id = ? AND student_id = ?" in txt
    assert "DELETE FROM logs" in txt and "student_id" in txt

# 17 student isolation cross-user
def test_student_cannot_access_other_student_task():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp = client.get("/student/task/999")
        assert resp.status_code == 404
        resp2 = client.get("/student/document/999")
        assert resp2.status_code == 404
        resp3 = client.get("/student/session/999")
        assert resp3.status_code == 404

def test_documents_template_csrf_and_routes():
    # ensure all student POST forms have csrf
    views = list(pathlib.Path("resources/views/student").rglob("*.html"))
    missing = []
    for p in views:
        txt = p.read_text(encoding="utf-8")
        if '<form' in txt.lower() and 'method="post"' in txt.lower():
            if 'csrf_token' not in txt.lower():
                missing.append(str(p))
    assert missing == [], f"Missing CSRF {missing}"
    # The document preview anchor is intentionally a JS-populated placeholder;
    # no other student templates should use href="#" as a dead route.
    placeholders = []
    for p in views:
        txt = p.read_text(encoding="utf-8")
        if 'href="#"' in txt:
            placeholders.append((str(p), txt.count('href="#"')))
    assert placeholders == [(str(pathlib.Path("resources/views/student/documents.html")), 1)]
    documents = pathlib.Path("resources/views/student/documents.html").read_text(encoding="utf-8")
    assert 'id="document-preview-open" href="#"' in documents
