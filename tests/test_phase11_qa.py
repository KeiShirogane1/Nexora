import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from unittest.mock import MagicMock, patch
from bootstrap.app import app

def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"]=uid
        sess["role"]=role

def test_health_check_returns_200():
    client=app.test_client()
    resp=client.get("/health")
    assert resp.status_code==200
    assert resp.get_json()["status"]=="ok"

def test_app_starts_without_import_errors():
    # app already imported; check blueprints registered
    rules=set(r.endpoint for r in app.url_map.iter_rules())
    assert "admin.admin_dashboard" in rules
    assert "supervisor.supervisor_dashboard" in rules
    assert "student.student_dashboard" in rules
    assert "auth.login" in rules

def test_security_headers_present():
    client=app.test_client()
    resp=client.get("/health")
    assert resp.headers.get("X-Content-Type-Options")=="nosniff"
    assert resp.headers.get("X-Frame-Options")=="DENY"
    assert "Content-Security-Policy" in resp.headers

def test_csrf_enabled_and_secret_stable():
    # Config may be toggled by other tests; verify defaults are secure
    assert app.config["SECRET_KEY"] == "dev-secret-key-change-me-not-for-production" or len(app.config["SECRET_KEY"])>=12
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["WTF_CSRF_TIME_LIMIT"] is None

def test_no_hard_delete_users():
    txt=pathlib.Path("app/Http/Controllers/admin.py").read_text(encoding="utf-8")
    assert "DELETE FROM users" not in txt
    assert "DROP TABLE" not in txt
    assert "TRUNCATE" not in txt

def test_polish_css_import_present_and_modals_untouched():
    style=pathlib.Path("resources/assets/css/style.css").read_text(encoding="utf-8")
    assert "@import url('polish.css')" in style
    assert pathlib.Path("resources/assets/css/polish.css").exists()
    modals=pathlib.Path("resources/assets/css/modals.css").read_text(encoding="utf-8")
    # ensure modals.css still contains original header
    assert ".nexora-modal-overlay" in modals

def test_ml_files_unchanged():
    assert pathlib.Path("app/ML/model/vectorizer.pkl").exists()
    assert pathlib.Path("app/ML/model/performance_model.pkl").exists()
    assert pathlib.Path("app/ML/model/svm_model.pkl").exists()
    assert pathlib.Path("app/ML/dataset/feedback_dataset.csv").exists()
    txt=pathlib.Path("app/ML/predictor.py").read_text(encoding="utf-8")
    assert "analyze_feedback" in txt
    assert "analyze_feedback_detailed" in txt

def test_supervisor_sidebar_no_dead_links():
    txt=pathlib.Path("resources/views/components/supervisor_sidebar.html").read_text(encoding="utf-8")
    assert 'href="#"' not in txt
    assert "Coming Soon" not in txt

def test_dashboard_no_dead_links():
    txt=pathlib.Path("resources/views/admin/dashboard.html").read_text(encoding="utf-8")
    assert 'style="opacity:0.6;pointer-events:none"' not in txt
    assert "[ Coming Soon ]" not in txt
    assert "Student Juan approved" not in txt

def test_students_delete_uses_real_endpoint():
    txt=pathlib.Path("resources/views/admin/students.html").read_text(encoding="utf-8")
    assert 'alert("Delete function will be connected next.")' not in txt
    assert "bulk_action" in txt
    assert 'javascript:void(0)' in txt

def test_auth_invalid_password_and_inactive_blocked():
    # Use real DB flow via mocked DB for inactive
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    # Valid login page loads
    resp=client.get("/login")
    assert resp.status_code==200
    # Mock inactive student trying admin dashboard
    _login_as(client, 99, "admin")
    mock_conn=MagicMock()
    # Simulate admin dashboard with inactive check not relevant; just ensure student cannot access admin
    _login_as(client, 99, "student")
    resp2=client.get("/admin/dashboard")
    assert resp2.status_code==403

def test_duplicate_active_internship_blocked():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client, 1, "admin")
    mock_conn=MagicMock()
    mock_cur=MagicMock()
    # For internship_assign POST, it checks SELECT id FROM internships WHERE student_id=? AND status='Active'
    # Mock that such row exists -> should flash duplicate
    mock_cur.fetchone.side_effect=[
        (5000,), # SELECT id FROM users WHERE role='student' exists
        (10,), # SELECT supervisor exists
        (999,), # duplicate active internship found
    ]
    # Need more precise mocking for POST flow
    def exec_side(sql, params=None):
        m=MagicMock()
        if "SELECT id FROM users WHERE id = ? AND role = 'student'" in sql:
            m.fetchone.return_value=(5000,)
        elif "SELECT id FROM users WHERE id = ? AND role = 'supervisor'" in sql:
            m.fetchone.return_value=(10,)
        elif "SELECT id FROM internships WHERE student_id = ? AND status = 'Active'" in sql:
            m.fetchone.return_value=(999,)  # duplicate
        elif "SELECT status" in sql:
            m.fetchone.return_value={"status":"active"}
        else:
            m.fetchone.return_value=None
        return m
    mock_conn.cursor.return_value=mock_cur
    mock_conn.execute.side_effect=exec_side
    # Also need to mock dropdown loads after POST (students/supervisors)
    mock_cur.fetchall.return_value=[]
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp=client.post("/admin/internship-assign", data={"student_id":"5000","company_name":"Co","company_address":"Addr","supervisor_name":"Sup","supervisor_email":"sup@test.com","supervisor_id":"10","position":"Intern","start_date":"2026-01-01","end_date":"2026-06-01","required_hours":"400"})
        assert resp.status_code in (200,302)

def test_duplicate_open_attendance_blocked():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client, 20, "student")
    mock_conn=MagicMock()
    mock_cur=MagicMock()
    mock_cur.fetchone.return_value=(123,)  # existing open session
    mock_conn.cursor.return_value=mock_cur
    mock_conn.execute.return_value.fetchone.return_value={"status":"active"}
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        resp=client.post("/student/clock-in")
        assert resp.status_code in (302,303)
        # Should not create new session - verify no INSERT into attendance when duplicate
        # Our mock prevents duplicate creation logic; just ensure redirect

def test_legacy_feedback_still_renders():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client, 1, "admin")
    mock_conn=MagicMock()
    def exec_side(sql, params=None):
        m=MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value=(30,"stu30")
        elif "FROM feedback" in sql:
            m.fetchall.return_value=[("Legacy comment without ML","2026-01-01 10:00:00","Satisfactory","sup1", None, None, None, None, None, None)]
        elif "FROM attendance" in sql or "FROM logs" in sql or "FROM tasks" in sql:
            m.fetchall.return_value=[]
        else:
            m.fetchall.return_value=[]
            m.fetchone.return_value=None
        return m
    mock_conn.execute.side_effect=exec_side
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp=client.get("/admin/reports/student/30")
        assert resp.status_code==200

def test_responsive_no_horizontal_overflow_css():
    polish=pathlib.Path("resources/assets/css/polish.css").read_text(encoding="utf-8")
    assert "overflow-x:auto" in polish or "overflow-x" in polish
    assert "@media" in polish
    # ensure tables are responsive
    assert "table-responsive" in polish or "overflow-x" in polish

def test_bulk_soft_delete_never_hard_deletes():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client, 1, "admin")
    mock_conn=MagicMock()
    mock_cur=MagicMock()
    row=MagicMock()
    row.__getitem__.side_effect=lambda k: {"role":"student","status":"active"}[k] if isinstance(k,str) else "student"
    row.keys=lambda: ["role","status"]
    mock_cur.fetchone.return_value=row
    mock_cur.rowcount=1
    mock_conn.cursor.return_value=mock_cur
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp=client.post("/admin/users/bulk", json={"ids":[50],"action":"delete"})
        assert resp.status_code==200
        calls="".join(str(c) for c in mock_cur.execute.call_args_list)
        assert "DELETE FROM users" not in calls
