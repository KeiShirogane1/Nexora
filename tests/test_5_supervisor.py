import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from unittest.mock import MagicMock, patch
from bootstrap.app import app

def _login_as(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role

def _mock_active_supervisor_conn(mock_conn=None, mock_cursor=None):
    """Helper to return mock that treats supervisor as active for before_request."""
    if mock_conn is None:
        mock_conn = MagicMock()
    if mock_cursor is None:
        mock_cursor = MagicMock()
    # before_request uses conn.execute(...).fetchone()
    mock_cursor_active = MagicMock()
    mock_cursor_active.fetchone.return_value = {"status": "active"}
    # default: execute returns cursor_active for first call, then others
    mock_conn.execute.return_value = mock_cursor_active
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor, mock_cursor_active

# 1. dashboard authorization
def test_supervisor_dashboard_requires_login():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/supervisor/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/login" in resp.headers.get("Location", "")

def test_supervisor_dashboard_student_forbidden():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    resp = client.get("/supervisor/dashboard")
    assert resp.status_code == 403

def test_supervisor_dashboard_ok_filtered():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # dashboard does 6 queries via cursor
    mock_cursor.fetchone.side_effect = [(2,), (1,), (3,), (5,), (1,)]  # total_interns, active_sessions etc loops may consume more but we mock cursor.fetchall for others
    mock_cursor.fetchall.side_effect = [
        [( "intern1", "2026-01-01"),],  # active_interns
        [("user1","content","2026-01-01", 20)],  # acts
        [("Task A","user1","Pending","2026-01-01")],  # recent_tasks
    ]
    mock_conn.cursor.return_value = mock_cursor
    # before_request status check via execute
    mock_active = MagicMock()
    mock_active.fetchone.return_value = {"status": "active"}
    mock_conn.execute.return_value = mock_active
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/dashboard")
        assert resp.status_code == 200
        assert b"Supervisor Dashboard" in resp.data

def test_inactive_supervisor_blocked():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    mock_inactive = MagicMock()
    mock_inactive.fetchone.return_value = {"status": "inactive"}
    mock_conn.execute.return_value = mock_inactive
    mock_conn.cursor.return_value = MagicMock()
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/dashboard")
        assert resp.status_code == 403
        assert b"deactivated" in resp.data.lower()

# 2. intern list ownership
def test_interns_shows_only_assigned():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # interns query returns 2 assigned
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status": "active"}
    # But view_interns uses conn.execute directly, not cursor
    mock_conn.execute.return_value.fetchall.return_value = [(20, "studentA", "BSIT", "1st Year", "Company X", "Intern", "Active"), (21, "studentB", None, None, None, None, None)]
    # Need to handle before_request execute vs view execute; split side_effect
    # before_request first call returns status active, second call (interns) returns rows
    call_count = {"n":0}
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
            m.fetchall.return_value = []
        elif "FROM users" in sql and "student_assignments" in sql:
            m.fetchall.return_value = [(20, "studentA", "BSIT", "1st Year", "Company X", "Intern", "Active")]
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/interns")
        assert resp.status_code == 200
        assert b"Assigned Students" in resp.data

# 3 & 4. student profile assigned vs unassigned
def test_assigned_student_profile_ok():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        elif "SELECT username" in sql:
            m.fetchone.return_value = ("studentA",)
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        # For view_student docs/tasks etc via conn.execute
        if "FROM attendance" in sql:
            m.fetchall.return_value = []
        if "FROM tasks" in sql:
            m.fetchall.return_value = []
        if "FROM documents" in sql:
            m.fetchall.return_value = []
        if "FROM feedback" in sql:
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec_side
    mock_conn.cursor.return_value = MagicMock()
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/student/20")
        assert resp.status_code == 200
        assert b"Student Profile" in resp.data or b"Overview" in resp.data

def test_unassigned_student_403():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/student/99")
        assert resp.status_code == 403

# 5 & 6 task creation authorized / unauthorized
def test_task_create_authorized():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        elif "SELECT username" in sql:
            m.fetchone.return_value = ("studentA",)
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec_side
    mock_conn.cursor.return_value = MagicMock()
    # also need cursor for assign_task POST? assign uses conn.execute for username then conn.execute for INSERT
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.post("/supervisor/student/20/assign-task", data={"task_title": "Valid Title", "task_description": "Valid description for task", "deadline": ""})
        assert resp.status_code in (302, 303)

def test_task_create_unauthorized():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.post("/supervisor/student/99/assign-task", data={"task_title": "Title", "task_description": "Desc"})
        assert resp.status_code == 403

def test_task_create_requires_title():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        elif "SELECT username" in sql:
            m.fetchone.return_value = ("studentA",)
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    mock_conn.cursor.return_value = MagicMock()
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.post("/supervisor/student/20/assign-task", data={"task_title": "", "task_description": "Valid desc"})
        assert resp.status_code in (302, 303)
        # Should not insert
        inserts = [c for c in mock_conn.execute.call_args_list if "INSERT INTO tasks" in str(c)]
        assert len(inserts) == 0

# 7 edit ownership
def test_task_edit_ownership():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    # editing other supervisor's task
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
        elif "FROM tasks" in sql and "supervisor_id" in sql:
            # edit_task checks WHERE id=? AND supervisor_id=?
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    # GET edit should 404
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/task/999/edit")
        assert resp.status_code == 404

def test_task_edit_authorized():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    mock_active = MagicMock()
    mock_active.fetchone.return_value = {"status":"active"}
    mock_conn.execute.return_value = mock_active
    mock_cursor = MagicMock()
    # HybridRow-like row
    row = MagicMock()
    def get_item(k):
        mapping = {0:1,1:20,2:"T",3:"D",4:None,5:1,6:0,7:"Pending", "id":1, "student_id":20, "task_title":"T", "task_description":"D", "deadline":None, "requires_submission":1, "allow_late_submission":0, "status":"Pending"}
        return mapping[k]
    row.__getitem__.side_effect = get_item
    row.keys.return_value = ["id","student_id","task_title","task_description","deadline","requires_submission","allow_late_submission","status"]
    mock_cursor.fetchone.return_value = row
    mock_conn.cursor.return_value = mock_cursor
    # Make execute for task fetch also return same row
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "FROM tasks" in sql and "supervisor_id" in sql:
            m.fetchone.return_value = row
        else:
            m.fetchone.return_value = row
        return m
    # Keep execute for before_request and task; cursor for edit
    # Use cursor path for edit: supervisor uses conn.execute for task, not cursor
    # So patch execute to return row for tasks
    orig_exec = mock_conn.execute
    def combined(sql, params=None):
        if "SELECT status" in sql or "FROM tasks" in sql:
            m = MagicMock()
            m.fetchone.return_value = row if "FROM tasks" in sql else {"status":"active"}
            return m
        return MagicMock()
    mock_conn.execute.side_effect = combined
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.post("/supervisor/task/1/edit", data={"task_title":"New Title Valid", "task_description":"New desc valid longer than five"})
        assert resp.status_code in (302,303,200)

# 8 delete ownership
def test_task_delete_ownership():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT student_id" in sql and "FROM tasks" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.post("/supervisor/task/999/delete")
        assert resp.status_code == 404
        # ensure GET not allowed
        resp2 = client.get("/supervisor/task/999/delete")
        assert resp2.status_code == 405

# 9 & 10 feedback
def test_feedback_authorized():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        with patch("app.Http.Controllers.supervisor.create_notification"):
            resp = client.post("/supervisor/student/20/feedback", data={"comment":"Great work on tasks", "label":"Excellent"})
            assert resp.status_code in (302,303)

def test_feedback_unauthorized():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.post("/supervisor/student/99/feedback", data={"comment":"test", "label":"Excellent"})
        assert resp.status_code == 403

def test_feedback_requires_comment():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.post("/supervisor/student/20/feedback", data={"comment":"", "label":"Excellent"})
        assert resp.status_code in (302,303)
        # should not insert
        inserts = [c for c in mock_conn.execute.call_args_list if "INSERT INTO feedback" in str(c)]
        assert len(inserts)==0

# 11 document authorization
def test_document_authorized_and_traversal_block():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    import tempfile, os
    tmpdir = tempfile.mkdtemp()
    original_upload = app.config.get("UPLOAD_FOLDER")
    # create a dummy file inside upload folder
    app.config["UPLOAD_FOLDER"] = tmpdir
    dummy_path = os.path.join(tmpdir, "doc.pdf")
    with open(dummy_path, "wb") as f:
        f.write(b"hello")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)  # assigned
        elif "FROM documents" in sql:
            # return doc with filepath inside tmpdir
            m.fetchone.return_value = {"id":1, "student_id":20, "filename":"doc.pdf", "filepath": dummy_path}
            m.fetchone.return_value = MagicMock()
            row = MagicMock()
            row.__getitem__.side_effect = lambda k: { "id":1, "student_id":20, "filename":"doc.pdf", "filepath":dummy_path, 0:1,1:20,2:"doc.pdf",3:dummy_path}[k]
            row.keys.return_value = ["id","student_id","filename","filepath"]
            m.fetchone.return_value = row
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/document/1")
        assert resp.status_code == 200
        assert b"hello" in resp.data
    # unassigned -> 403
    def exec_side2(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = None
        elif "FROM documents" in sql:
            row = MagicMock()
            row.__getitem__.side_effect = lambda k: { "id":1, "student_id":20, "filename":"doc.pdf", "filepath":dummy_path}[k]
            row.keys.return_value = ["id","student_id","filename","filepath"]
            m.fetchone.return_value = row
        else:
            m.fetchone.return_value = None
        return m
    mock_conn2 = MagicMock()
    mock_conn2.execute.side_effect = exec_side2
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn2):
        resp = client.get("/supervisor/document/1")
        assert resp.status_code == 403
    # traversal block: filepath outside base
    evil_path = "/etc/passwd"
    def exec_side3(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        elif "FROM documents" in sql:
            row = MagicMock()
            row.__getitem__.side_effect = lambda k: { "id":1, "student_id":20, "filename":"evil.pdf", "filepath":evil_path}[k]
            row.keys.return_value = ["id","student_id","filename","filepath"]
            m.fetchone.return_value = row
        return m
    mock_conn3 = MagicMock()
    mock_conn3.execute.side_effect = exec_side3
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn3):
        resp = client.get("/supervisor/document/1")
        assert resp.status_code in (403,404)
    # restore upload folder
    app.config["UPLOAD_FOLDER"] = original_upload
    import shutil
    try:
        shutil.rmtree(tmpdir)
    except:
        pass

def test_document_notfound_404():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "FROM documents" in sql:
            m.fetchone.return_value = None
        elif "SELECT 1 FROM student_assignments" in sql:
            # not reached because doc not found first, but before_request still
            m.fetchone.return_value = (1,)
        else:
            m.fetchone.return_value = None
        return m
    # We need ordering: view_document first fetches doc, before that before_request status. But doc not found should 404 before assignment check
    # view_document does SELECT doc first before _is_assigned? Actually it fetches doc then checks assignment, so if doc None -> 404
    # mock execute for doc None
    mock_conn.execute.side_effect = exec_side
    # But view_document does conn.execute for doc; need to handle doc None case without assignment
    # Simpler: mock to return None for doc
    def exec2(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "FROM documents" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec2
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/document/999")
        assert resp.status_code == 404

# 13 & 14 CSRF
def test_assign_task_csrf_rejection():
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    # Need status active for before_request, but CSRF will block before DB?
    # CSRF check happens before route logic, so we just need session
    resp = client.post("/supervisor/student/20/assign-task", data={"task_title":"T", "task_description":"D"})
    assert resp.status_code == 400

def test_feedback_csrf_acceptance_with_token():
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 5
        sess["role"] = "supervisor"
    resp0 = client.get("/login")
    assert resp0.status_code == 200
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', resp0.get_data(as_text=True))
    assert m, "CSRF token not found"
    token = m.group(1)
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        mm = MagicMock()
        if "SELECT status" in sql:
            mm.fetchone.return_value = {"status":"active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            mm.fetchone.return_value = (1,)
        else:
            mm.fetchone.return_value = None
        return mm
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        with patch("app.Http.Controllers.supervisor.create_notification"):
            resp = client.post("/supervisor/student/20/feedback", data={"comment":"Great job well done valid", "label":"Excellent", "csrf_token": token}, follow_redirects=False)
            assert resp.status_code != 400, f"CSRF valid token should not be 400, got {resp.status_code} {resp.data[:200]}"
            assert resp.status_code in (302,303)

# 15 POST-only
def test_delete_requires_post():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/task/1/delete")
        assert resp.status_code == 405

def test_review_requires_post():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/task/1/review")
        assert resp.status_code == 405

def test_reopen_requires_post():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp = client.get("/supervisor/task/1/reopen")
        assert resp.status_code == 405

# 16 PostgreSQL-compatible SQL
def test_sql_uses_question_marks():
    txt = pathlib.Path("app/Http/Controllers/supervisor.py").read_text(encoding="utf-8")
    assert "?" in txt
    # Ensure no %s literal SQL (should use ? and let PostgresCursor convert)
    # Allow %s only in python string formatting, not SQL
    assert "using_postgres" in pathlib.Path("app/Models/db.py").read_text(encoding="utf-8")
    # Check all execute calls in supervisor use ? not %s
    import re
    sql_lines = [l for l in txt.split("\n") if "SELECT" in l or "INSERT" in l or "UPDATE" in l]
    for line in sql_lines:
        if "SELECT" in line or "INSERT" in line:
            assert "%s" not in line or "format" in line.lower()

def test_unauthenticated_redirects():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    for path in ["/supervisor/dashboard", "/supervisor/interns", "/supervisor/student/20", "/supervisor/task/1", "/supervisor/document/1"]:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (302,303), f"{path} should redirect"

def test_admin_cannot_access_supervisor():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    resp = client.get("/supervisor/dashboard")
    assert resp.status_code == 403

def test_student_cannot_access_supervisor():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    resp = client.get("/supervisor/interns")
    assert resp.status_code == 403
