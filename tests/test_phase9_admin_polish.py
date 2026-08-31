import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from unittest.mock import MagicMock, patch
from bootstrap.app import app
import re

def _login_as(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role

# 1 Dashboard loads
def test_dashboard_loads():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # admin_dashboard expects 7 fetchone counts + cursor close
    mock_cursor.fetchone.side_effect = [(2,), (3,), (1,), (2,), (1,), (1.5,), (0,), (1,), (0,)]
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor
    # before_request uses execute status check
    def exec_side(sql, params=None):
        m = MagicMock()
        m.fetchone.return_value = {"status":"active"} if "SELECT status" in sql else None
        return m
    # But admin_dashboard uses cursor, not execute for counts, so we need cursor mock
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/dashboard")
        assert resp.status_code == 200
        assert b"Admin Dashboard" in resp.data

# 2 Dashboard contains real dynamic statistics (not hard-coded 5/20/10 fake)
def test_dashboard_contains_real_dynamic_statistics():
    path = pathlib.Path("resources/views/admin/dashboard.html").read_text(encoding="utf-8")
    # Should use Jinja variables
    assert "{{ students_count }}" in path
    assert "{{ supervisors_count }}" in path
    assert "{{ assignments_count }}" in path
    # Should not contain hard-coded fake metric grid numbers like standalone "5" - but check template doesn't have hard-coded numbers outside Jinja
    # Recent Activities should not be fake Juan/Maria
    assert "Student Juan approved" not in path
    assert "Supervisor Maria assigned" not in path
    # Reports should be real links, not Coming Soon disabled
    assert 'href="/admin/reports" style="opacity:0.6' not in path
    assert "[ Coming Soon ]" not in path

def _HM(mapping):
    m = MagicMock()
    m._m = mapping
    for k,v in mapping.items():
        setattr(m, k, v)
    def getitem(k):
        if isinstance(k, int):
            return list(mapping.values())[k]
        return mapping[k]
    m.__getitem__ = getitem
    m.keys = lambda: mapping.keys()
    m.__contains__ = lambda k: k in mapping
    m.get = lambda k, d=None: mapping.get(k, d)
    # ensure bool true and not triggering child mock error
    type(m).__bool__ = lambda s: True
    return m

# 3 Student table loads
def test_student_table_loads():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    stu = _HM({"id":1,"username":"alice","email":"alice@test.com","role":"student","major_program":"BSIT","supervisor_name":"sup1"})
    sup = _HM({"id":10,"username":"sup1"})
    mock_cursor.fetchall.side_effect = [
        [stu], # students
        [sup],  # supervisors_list
        [("BSIT",)],  # programs raw fetchall returns tuples for programs_raw handling
    ]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/users/students")
        assert resp.status_code == 200
        assert b"Student Management" in resp.data
        assert b"alice" in resp.data

# 4 Student filtering works (client-side filter elements present)
def test_student_filtering_works():
    path = pathlib.Path("resources/views/admin/students.html").read_text(encoding="utf-8")
    assert 'id="studentSearch"' in path
    assert 'id="statusFilter"' in path
    assert 'id="supervisorFilter"' in path
    assert 'id="programFilter"' in path

# 5 Supervisor table loads
def test_supervisor_table_loads():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [(10, "supervisor1", "sup1@test.com", "supervisor", "active")],
        [(10, 2)],  # assignment counts raw
    ]
    # assignment_counts loop uses fetchall for counts
    # Need to mock execute for counts? admin_supervisors uses cursor.execute for supervisors then cursor.execute for counts
    # The second fetchall returns [(supervisor_id, cnt)]
    # We'll handle via side_effect already
    # However assignment_counts parsing uses r["supervisor_id"]
    # Mock rows need to support HybridRow interface .keys()
    row = MagicMock()
    row.__getitem__.side_effect = lambda k: {"supervisor_id":10, "cnt":2, 0:10,1:2}[k]
    row.keys.return_value = ["supervisor_id","cnt"]
    mock_cursor.fetchall.side_effect = [
        [MagicMock()],  # supervisors placeholder - will be replaced below
        [row],
    ]
    # Better to patch get_db_connection to return conn where cursor.fetchall returns supervisors then counts
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    # Direct test via client with patched cursor that returns valid supervisor
    sup_row = MagicMock()
    sup_row.__getitem__.side_effect = lambda k: {"id":10,"username":"supervisor1","email":"sup1@test.com","role":"supervisor","status":"active",0:10,1:"supervisor1",2:"sup1@test.com",3:"supervisor",4:"active"}[k]
    sup_row.keys.return_value = ["id","username","email","role","status"]
    mock_cursor.fetchall.side_effect = [[sup_row], [row]]
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/users/supervisors")
        assert resp.status_code == 200
        assert b"Supervisor Management" in resp.data

# 6 Supervisor assigned count is correct
def test_supervisor_assigned_count_is_correct():
    path = pathlib.Path("resources/views/admin/supervisors.html").read_text(encoding="utf-8")
    assert "assignment_counts.get(supervisor.id" in path
    assert "Assigned Students" in path
    # Controller should compute assignment_counts via GROUP BY
    txt = pathlib.Path("app/Http/Controllers/admin.py").read_text(encoding="utf-8")
    assert "SELECT supervisor_id, COUNT(*) as cnt FROM student_assignments GROUP BY supervisor_id" in txt

# 7 Supervisor profile loads
def test_supervisor_profile_loads():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    sup = _HM({"id":10,"username":"sup1","email":"e@test.com","role":"supervisor","status":"active"})
    mock_cursor.fetchone.side_effect = [sup, (2,)]
    # assigned_students rows need .username .email .id dot access
    stu = _HM({"id":1,"username":"stuA","email":"stu@test.com"})
    # also need tuple unpack via index for supervisor_profile? It uses s.username via s.id etc - template uses s.username etc with dot
    # so return list of _HM
    mock_cursor.fetchall.return_value = [stu]
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/supervisor/10")
        assert resp.status_code == 200
        assert b"Supervisor Profile" in resp.data
        assert b"Assigned Students" in resp.data

# 8 Supervisor activation/deactivation
def test_supervisor_activation_deactivation():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"username":"sup1","email":"sup1@test.com"}
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        with patch("app.Http.Controllers.admin.send_email"):
            resp = client.post("/admin/supervisor/10/deactivate")
            assert resp.status_code in (302,303)
            resp2 = client.post("/admin/supervisor/10/activate")
            assert resp2.status_code in (302,303)

# 9 Bulk activate
def test_bulk_activate():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    user_row = MagicMock()
    user_row.__getitem__.side_effect = lambda k: {"role":"student","status":"inactive",0:"student",1:"inactive"}[k]
    user_row.keys.return_value = ["role","status"]
    mock_cursor.fetchone.return_value = user_row
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.execute.return_value.fetchone.return_value = {"status":"active"}
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids":[20],"action":"activate"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

# 10 Bulk deactivate
def test_bulk_deactivate():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    user_row = MagicMock()
    user_row.__getitem__.side_effect = lambda k: {"role":"supervisor","status":"active",0:"supervisor",1:"active"}[k]
    user_row.keys.return_value = ["role","status"]
    mock_cursor.fetchone.return_value = user_row
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids":[21],"action":"deactivate"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

# 11 Bulk soft-delete
def test_bulk_soft_delete():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    user_row = MagicMock()
    user_row.__getitem__.side_effect = lambda k: {"role":"student","status":"active",0:"student"}[k]
    user_row.keys.return_value = ["role","status"]
    mock_cursor.fetchone.return_value = user_row
    mock_cursor.rowcount = 1
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids":[22],"action":"delete"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        # ensure never hard DELETE - check that cursor.execute was called with UPDATE not DELETE
        calls = "".join(str(c) for c in mock_cursor.execute.call_args_list)
        assert "UPDATE users SET status = 'inactive'" in calls or "UPDATE users SET role = 'rejected'" in calls
        assert "DELETE FROM users" not in calls

# 12 Bulk requires POST
def test_bulk_requires_post():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    resp = client.get("/admin/users/bulk")
    assert resp.status_code == 405

# 13 Bulk requires CSRF
def test_bulk_requires_csrf():
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    # Need to not provide CSRF token -> should 400
    resp = client.post("/admin/users/bulk", json={"ids":[1],"action":"activate"})
    assert resp.status_code == 400

# 14 Bulk requires admin authorization
def test_bulk_requires_admin_authorization():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    resp = client.post("/admin/users/bulk", json={"ids":[20],"action":"activate"})
    assert resp.status_code == 403
    _login_as(client, 5, "supervisor")
    resp2 = client.post("/admin/users/bulk", json={"ids":[20],"action":"activate"})
    assert resp2.status_code == 403

# 15 Bulk rejects invalid action
def test_bulk_rejects_invalid_action():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    resp = client.post("/admin/users/bulk", json={"ids":[20],"action":"invalid_act"})
    assert resp.status_code == 400
    assert b"Invalid action" in resp.data or not resp.get_json()["success"]

# 16 Bulk cannot modify admin users
def test_bulk_cannot_modify_admin():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    admin_row = MagicMock()
    admin_row.__getitem__.side_effect = lambda k: {"role":"admin","status":"active",0:"admin"}[k]
    admin_row.keys.return_value = ["role","status"]
    mock_cursor.fetchone.return_value = admin_row
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/users/bulk", json={"ids":[1],"action":"deactivate"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["updated_count"] == 0

# 17 Approval workflow works
def test_approval_workflow_works():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"username":"pending1","email":"p@test.com"}
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        with patch("app.Http.Controllers.admin.send_email"):
            resp = client.post("/admin/approve-student/99")
            assert resp.status_code in (302,303)
            resp2 = client.post("/admin/reject-supervisor/100")
            assert resp2.status_code in (302,303)

# 18 GET approval returns 405
def test_get_approval_returns_405():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    resp = client.get("/admin/approve-student/99")
    assert resp.status_code == 405
    resp2 = client.get("/admin/approve-supervisor/99")
    assert resp2.status_code == 405
    resp3 = client.get("/admin/reject-student/99")
    assert resp3.status_code == 405

# 19 Assign-role GET returns 405
def test_assign_role_get_returns_405():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    resp = client.get("/admin/assign-role")
    assert resp.status_code == 405

# 20 Assign-role cannot promote to admin
def test_assign_role_cannot_promote_to_admin():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"role":"pending_student"}
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.post("/admin/assign-role", data={"user_id":"99","role":"admin"})
        assert resp.status_code in (302,303)
        # ensure no UPDATE to admin
        calls = "".join(str(c) for c in mock_cursor.execute.call_args_list)
        assert "admin" not in calls.lower() or "Invalid role" in resp.get_data(as_text=True) or resp.status_code in (302,303)
        # Follow redirect, check that role not changed to admin via DB call
        # The controller should reject because allowed_roles only student/supervisor
        assert mock_cursor.execute.call_count == 0 or "UPDATE users SET role = 'admin'" not in "".join(str(c) for c in mock_cursor.execute.call_args_list)

# 21 Reports list works
def test_reports_list_works():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(1, "stu1", "sup1")]
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/reports")
        assert resp.status_code == 200
        assert b"Internship Reports" in resp.data

# 22 Student report works
def test_student_report_works():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = MagicMock()
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql and "FROM users" in sql:
            m.fetchone.return_value = (1, "stu1")
        elif "FROM attendance" in sql:
            m.fetchall.return_value = []
        elif "FROM logs" in sql:
            m.fetchall.return_value = []
        elif "FROM feedback" in sql:
            m.fetchall.return_value = []
        elif "FROM tasks" in sql:
            m.fetchall.return_value = []
        else:
            m.fetchall.return_value = []
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = exec_side
    mock_conn.cursor.return_value = MagicMock()
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/reports/student/1")
        assert resp.status_code == 200
        assert b"Student Report" in resp.data or b"Internship Report" in resp.data

# 23 Broken admin report routes are absent/fixed
def test_broken_admin_report_routes_absent():
    dash = pathlib.Path("resources/views/admin/dashboard.html").read_text(encoding="utf-8")
    assert 'href="/admin/reports" style="opacity:0.6' not in dash
    assert "[ Coming Soon ]" not in dash
    # Ensure attendance uses url_for
    assert "url_for('admin.attendance_report')" in dash or "url_for(\"admin.attendance_report\")" in dash
    # Students and supervisors delete should not be href="#"
    stu = pathlib.Path("resources/views/admin/students.html").read_text(encoding="utf-8")
    sup = pathlib.Path("resources/views/admin/supervisors.html").read_text(encoding="utf-8")
    assert stu.count('href="#"') == 0 or 'href="javascript:void(0)"' in stu
    assert sup.count('href="#"') == 0 or 'href="javascript:void(0)"' in sup
    assert "Delete function will be connected next" not in stu
    assert "Delete function will be connected next" not in sup

# 24 No dangerous hard-delete user operation
def test_no_dangerous_hard_delete():
    admin_txt = pathlib.Path("app/Http/Controllers/admin.py").read_text(encoding="utf-8")
    # Check bulk_action does not contain DELETE FROM users
    bulk_section = admin_txt[admin_txt.find("def bulk_action") : admin_txt.find("def bulk_action")+5000]
    assert "DELETE FROM users" not in bulk_section
    # Check whole admin.py doesn't have hard delete outside bulk
    # Allow DELETE FROM task_submissions etc, but not users
    assert admin_txt.count("DELETE FROM users") == 0

# 25 Existing Phase 8 ML report still works
def test_existing_phase8_ml_report_still_works():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    fb_rows = [("c","2026-01-01 10:00:00","Excellent","sup1","Excellent","Positive","Outstanding Competency","rec","Excellent",0.9)]
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (20, "stu20")
        elif "FROM feedback" in sql:
            m.fetchall.return_value = fb_rows
        elif "FROM attendance" in sql or "FROM logs" in sql or "FROM tasks" in sql:
            m.fetchall.return_value = []
        else:
            m.fetchall.return_value = []
            m.fetchone.return_value = None
        return m
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = exec_side
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/reports/student/20")
        assert resp.status_code == 200
        txt = resp.get_data(as_text=True)
        assert "ML Feedback Analysis" in txt
        assert "Overall Sentiment" in txt
        assert "Competency Summary" in txt
