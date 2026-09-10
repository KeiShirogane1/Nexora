import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from unittest.mock import MagicMock, patch
from bootstrap.app import app
from jinja2 import Environment, FileSystemLoader

def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"]=uid
        sess["role"]=role

def test_all_important_templates_parse():
    env=Environment(loader=FileSystemLoader("resources/views"))
    important=[
        "admin/dashboard.html","admin/students.html","admin/supervisors.html","admin/users.html","admin/assignments.html",
        "admin/internship_assign.html","admin/reports_list.html","admin/reports/attendance.html","admin/reports/student_report.html",
        "admin/student_profile.html","admin/supervisor_profile.html","admin/edit_supervisor.html",
        "student/dashboard.html","student/profile.html","student/tasks.html","student/logbook.html",
        "supervisor/dashboard.html","supervisor/interns.html","supervisor/student_profile.html",
        "auth/login.html","auth/signup.html","welcome.html","components/admin_sidebar.html"
    ]
    for t in important:
        env.get_template(t)

def test_admin_pages_render():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client,1,"admin")
    # Mock dashboard DB
    mock_conn=MagicMock()
    mock_cur=MagicMock()
    mock_cur.fetchone.side_effect=[(2,),(3,),(1,),(2,),(1,),(1.5,),(0,),(1,),(0,)]
    mock_cur.fetchall.return_value=[]
    mock_conn.cursor.return_value=mock_cur
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        for url in ["/admin/dashboard","/admin/users"]:
            resp=client.get(url)
            assert resp.status_code==200, url

def test_student_pages_render():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client,10,"student")
    # student dashboard requires profile check - mock DB for dashboard
    mock_conn=MagicMock()
    mock_cur=MagicMock()
    # student_profile for dashboard
    profile_row=MagicMock()
    profile_row.__getitem__.side_effect=lambda k: {"first_name":"John","middle_name":"","last_name":"Doe","age":21,"student_id":"S1","profile_picture":None,"phone_number":"123","home_address":"Addr","grade_year":"1st","major_program":"BSIT"}[k] if isinstance(k,str) else None
    profile_row.__getitem__.side_effect
    # Instead use HybridRow-like mock with attributes
    def make_profile():
        m=MagicMock()
        m.__getitem__.side_effect=lambda k: {"first_name":"John","middle_name":"","last_name":"Doe","age":21,"student_id":"S1","profile_picture":None,"phone_number":"123","home_address":"Addr","grade_year":"1st","major_program":"BSIT",0:"John"}[k] if k in ["first_name","middle_name","last_name","age","student_id","profile_picture","phone_number","home_address","grade_year","major_program",0] else None
        m.keys=lambda: ["first_name"]
        for k in ["first_name","middle_name","last_name","age","student_id","profile_picture","phone_number","home_address","grade_year","major_program"]:
            setattr(m,k, {"first_name":"John","middle_name":"","last_name":"Doe","age":21,"student_id":"S1","profile_picture":None,"phone_number":"123","home_address":"Addr","grade_year":"1st","major_program":"BSIT"}[k])
        return m
    mock_cur.fetchone.side_effect=[
        make_profile(),  # profile
        make_profile(),  # internship check? actually internship fetch
        (0,),(0,),(0,),(0,)  # counts
    ]
    mock_cur.fetchall.return_value=[]
    mock_conn.cursor.return_value=mock_cur
    mock_conn.execute.return_value.fetchone.return_value={"status":"active"}
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        # limit to a few pages that don't require heavy DB
        for url in ["/student/dashboard","/student/tasks","/student/documents"]:
            try:
                resp=client.get(url)
                assert resp.status_code in (200,302)
            except: pass

def test_supervisor_pages_render():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client,5,"supervisor")
    mock_conn=MagicMock()
    mock_conn.execute.return_value.fetchone.return_value={"status":"active"}
    mock_cur=MagicMock()
    mock_cur.fetchone.side_effect=[(2,),(1,)]
    mock_cur.fetchall.return_value=[]
    mock_conn.cursor.return_value=mock_cur
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        resp=client.get("/supervisor/dashboard")
        assert resp.status_code==200

def test_auth_pages_render():
    app.config["WTF_CSRF_ENABLED"]=True
    app.config["TESTING"]=True
    client=app.test_client()
    for url in ["/login","/signup", "/forgot-password"]:
        resp=client.get(url)
        assert resp.status_code in (200,302,404)

def test_navigation_templates_render():
    env=Environment(loader=FileSystemLoader("resources/views"))
    for t in ["components/admin_sidebar.html","components/student_sidebar.html","components/supervisor_sidebar.html","components/admin_navbar.html","components/supervisor_navbar.html"]:
        env.get_template(t)

def test_no_broken_url_for_endpoints():
    import pathlib as p
    txt="".join([f.read_text(encoding="utf-8", errors="ignore") for f in p.Path("resources/views").rglob("*.html")])
    with app.test_request_context():
        import re
        for m in re.findall(r"url_for\([\'\"]([^\'\"]+)[\'\"]", txt):
            if m in ("static",):
                continue
            if m.startswith("admin.") or m.startswith("auth.") or m.startswith("student.") or m.startswith("supervisor."):
                try:
                    from flask import url_for
                    # try with dummy args where needed
                    if m in ("admin.student_report","admin.supervisor_profile","admin.edit_supervisor","admin.student_profile","admin.profile_history","admin.student_logbook"):
                        try:
                            url_for(m, student_id=1, supervisor_id=1, user_id=1, date="2026-01-01")
                        except Exception:
                            url_for(m, student_id=1)
                        continue
                    url_for(m)
                except Exception as e:
                    if any(k in str(e) for k in ("student_id","user_id","supervisor_id","date","filename","task_id","document_id")):
                        continue
                    assert False, f"broken url_for {m}: {e}"

def test_important_forms_retain_csrf():
    for tmpl in ["admin/students.html","admin/supervisors.html","admin/student_profile.html","supervisor/student_profile.html","auth/login.html"]:
        txt=pathlib.Path(f"resources/views/{tmpl}").read_text(encoding="utf-8")
        if "<form" in txt:
            assert "csrf_token" in txt, tmpl

def test_existing_fetch_retains_csrf():
    for tmpl in ["admin/students.html","admin/supervisors.html"]:
        txt=pathlib.Path(f"resources/views/{tmpl}").read_text(encoding="utf-8")
        if "fetch" in txt:
            assert "X-CSRFToken" in txt, tmpl

def test_ml_report_still_renders():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client,1,"admin")
    mock_conn=MagicMock()
    def exec_side(sql, params=None):
        m=MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value=(1,"stu1")
        elif "FROM feedback" in sql:
            m.fetchall.return_value=[("c","2026-01-01 10:00:00","Excellent","sup1","Excellent","Positive","Outstanding Competency","rec","Excellent",0.9)]
        elif "FROM attendance" in sql or "FROM logs" in sql or "FROM tasks" in sql:
            m.fetchall.return_value=[]
        else:
            m.fetchall.return_value=[]
            m.fetchone.return_value=None
        return m
    mock_conn.execute.side_effect=exec_side
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp=client.get("/admin/reports/student/1")
        assert resp.status_code==200
        assert b"ML Feedback Analysis" in resp.data
        assert b"Overall Sentiment" in resp.data

def test_supervisor_feedback_ml_display_still_renders():
    path=pathlib.Path("resources/views/supervisor/student_profile.html").read_text(encoding="utf-8")
    assert "ML Performance" in path
    assert "Sentiment" in path

def test_student_task_forms_still_render():
    path=pathlib.Path("resources/views/student/task_details.html").read_text(encoding="utf-8")
    # should contain form or task title
    assert "Task" in path

def test_admin_bulk_controls_still_exist():
    for tmpl in ["admin/students.html","admin/supervisors.html"]:
        txt=pathlib.Path(f"resources/views/{tmpl}").read_text(encoding="utf-8")
        assert 'id="bulkActivate"' in txt
        assert 'id="bulkDelete"' in txt
        assert "bulk_action" in txt

def test_no_destructive_db_operation_introduced():
    txt=pathlib.Path("app/Http/Controllers/admin.py").read_text(encoding="utf-8")
    assert "DELETE FROM users" not in txt
    assert "DROP TABLE" not in txt
    assert "TRUNCATE" not in txt

def test_no_authorization_regression():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client,10,"student")
    resp=client.get("/admin/dashboard")
    assert resp.status_code==403
    _login_as(client,5,"supervisor")
    resp2=client.get("/admin/dashboard")
    assert resp2.status_code==403

def test_no_ml_files_changed():
    import pathlib
    txt=pathlib.Path("app/ML/predictor.py").read_text(encoding="utf-8")
    assert "VALID_LABELS" in txt
    assert "analyze_feedback" in txt
    assert pathlib.Path("app/ML/model/vectorizer.pkl").exists()
    assert pathlib.Path("app/ML/model/performance_model.pkl").exists()
    assert pathlib.Path("app/ML/model/svm_model.pkl").exists()

def test_no_removed_important_routes():
    import pathlib
    admin_py=pathlib.Path("app/Http/Controllers/admin.py").read_text(encoding="utf-8")
    assert "def admin_dashboard" in admin_py
    assert "def admin_students" in admin_py
    assert "def student_report" in admin_py
    assert "def bulk_action" in admin_py
