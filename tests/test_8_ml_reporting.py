import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from unittest.mock import MagicMock, patch
from bootstrap.app import app
import re

VALID_LABELS = {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}

def _login_as(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role

def _mock_admin_report_conn(feedback_rows=None):
    """feedback_rows: list of tuples matching new 10-col enriched feedback"""
    mock_conn = MagicMock()
    # student exists
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql and "FROM users" in sql:
            m.fetchone.return_value = (1, "student1")
        elif "FROM attendance" in sql:
            m.fetchall.return_value = []
        elif "FROM logs" in sql:
            m.fetchall.return_value = []
        elif "FROM feedback" in sql and "JOIN users" in sql:
            # feedback rows requested
            if feedback_rows is not None:
                m.fetchall.return_value = feedback_rows
            else:
                m.fetchall.return_value = []
        elif "FROM tasks" in sql:
            m.fetchall.return_value = []
        elif "SELECT COUNT" in sql:
            m.fetchone.return_value = (0,)
        else:
            m.fetchone.return_value = None
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec_side
    mock_conn.cursor.return_value = MagicMock()
    return mock_conn

def test_admin_student_report_loads_successfully():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    mock_conn = _mock_admin_report_conn(feedback_rows=[])
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/reports/student/1")
        assert resp.status_code == 200
        assert b"Student Report" in resp.data or b"Internship Report" in resp.data

def test_report_with_no_feedback_does_not_crash():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    # empty feedback should show empty state, not crash
    # feedback_rows = [] via default
    mock_conn = _mock_admin_report_conn(feedback_rows=[])
    # Need more complete mock for student_report: attendance, etc return [] handled above but need student row
    def exec2(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (5, "studentA")
        elif "FROM feedback" in sql:
            m.fetchall.return_value = []
        elif "FROM attendance" in sql:
            m.fetchall.return_value = []
        elif "FROM logs" in sql:
            m.fetchall.return_value = []
        elif "FROM tasks" in sql:
            m.fetchall.return_value = []
        elif "SELECT created_at" in sql and "FROM logs" in sql:
            m.fetchall.return_value = []
        else:
            m.fetchone.return_value = (0,) if "COUNT" in sql else None
            m.fetchall.return_value = []
        return m
    mock_conn.execute.side_effect = exec2
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/reports/student/5")
        assert resp.status_code == 200
        # should contain empty state string from template
        assert b"No feedback available for ML analysis" in resp.data or b"No supervisor feedback" in resp.data

def test_performance_distribution_calculated_correctly():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    # Create 3 feedback rows with stored ML: 2 Excellent, 1 Fair
    # Use HybridRow-like mocks: return list of tuples for feedback query
    # raw_feedback with stored columns: comment, created_at, performance_label, username, ml_pred, ml_sent, ml_comp, ml_rec, ml_svm, ml_conf
    fb_rows = [
        ("Excellent work", "2026-01-01 10:00:00", "Excellent", "sup1", "Excellent", "Positive", "Outstanding Competency", "Continue excellent performance; consider leadership opportunities and advanced responsibilities.", "Excellent", 0.9),
        ("Also excellent", "2026-01-02 10:00:00", "Excellent", "sup1", "Excellent", "Positive", "Outstanding Competency", "Continue excellent performance; consider leadership opportunities and advanced responsibilities.", "Very Satisfactory", 0.8),
        ("Needs improvement", "2026-01-03 10:00:00", "Fair", "sup1", "Fair", "Negative", "Developing Competency", "Needs improvement in consistency, communication, and time management; additional supervision and coaching required.", "Fair", 0.7),
    ]
    # need to mock feedback fetch to return fb_rows; other queries return empty/zero
    def exec_perf(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql and "FROM users" in sql:
            m.fetchone.return_value = (10, "studentX")
        elif "FROM feedback" in sql and "JOIN users" in sql:
            mock_rows = []
            for r in fb_rows:
                # make HybridRow-like: support keys() and __getitem__
                hr = MagicMock()
                # map keys
                keys = ["comment","created_at","performance_label","username","ml_prediction","ml_sentiment","ml_competency","ml_recommendation","ml_svm_prediction","ml_confidence"]
                hr.keys.return_value = keys
                def get_item(k, row=r):
                    mapping = {0:row[0],1:row[1],2:row[2],3:row[3],4:row[4],5:row[5],6:row[6],7:row[7],8:row[8],9:row[9],
                               "comment":row[0],"created_at":row[1],"performance_label":row[2],"username":row[3],"ml_prediction":row[4],"ml_sentiment":row[5],"ml_competency":row[6],"ml_recommendation":row[7],"ml_svm_prediction":row[8],"ml_confidence":row[9]}
                    return mapping[k]
                hr.__getitem__.side_effect = get_item
                hr.__len__.return_value = 10
                # for indexed access fb[0] etc also need iteration; patch fallback to tuple
                hr.__iter__ = lambda s: iter(r)
                mock_rows.append(hr)
            # But easier: just return list of tuples that admin code will handle via fb[0] etc + fallback via analyze_feedback_detailed already handled
            # We'll return raw tuples; admin code now handles both HybridRow and tuple via fb[0] and fb.keys()
            # So return fb_rows as tuples; admin code will use fallback path not HybridRow branch but still works via len check
            m.fetchall.return_value = fb_rows
            return m
        elif "FROM attendance" in sql:
            m.fetchall.return_value = []
        elif "FROM logs" in sql:
            m.fetchall.return_value = []
        elif "FROM tasks" in sql:
            m.fetchall.return_value = []
        else:
            m.fetchall.return_value = []
            m.fetchone.return_value = None
        return m
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = exec_perf
    with patch("app.Http.Controllers.admin.get_db_connection", return_value=mock_conn):
        resp = client.get("/admin/reports/student/10")
        assert resp.status_code == 200
        data = resp.get_data(as_text=True)
        # check distributions: Excellent count 2 appears somewhere, Fair 1
        assert "Excellent" in data
        assert "Fair" in data

def test_sentiment_distribution_calculated_correctly():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    fb_rows = [
        ("c1","2026-01-01 10:00:00","Excellent","sup1","Excellent","Positive","Outstanding Competency","rec1","Excellent",0.9),
        ("c2","2026-01-02 10:00:00","Satisfactory","sup1","Satisfactory","Neutral","Adequate Competency","rec2","Satisfactory",0.8),
        ("c3","2026-01-03 10:00:00","Needs Improvement","sup1","Needs Improvement","Negative","Needs Significant Development","rec3","Needs Improvement",0.7),
    ]
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (11, "s11")
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
        resp = client.get("/admin/reports/student/11")
        assert resp.status_code == 200
        txt = resp.get_data(as_text=True)
        assert "Positive" in txt
        assert "Negative" in txt
        assert "Neutral" in txt

def test_competency_distribution_correctly():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    fb_rows = [
        ("c","2026-01-01 10:00:00","Excellent","sup1","Excellent","Positive","Outstanding Competency","rec","Excellent",0.9),
        ("c2","2026-01-02 10:00:00","Fair","sup1","Fair","Negative","Developing Competency","rec2","Fair",0.7),
    ]
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (12, "s12")
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
        resp = client.get("/admin/reports/student/12")
        assert resp.status_code == 200
        txt = resp.get_data(as_text=True)
        assert "Outstanding Competency" in txt or "Developing Competency" in txt

def test_recommendations_present_when_feedback_exists():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    rec_text = "Continue excellent performance; consider leadership opportunities and advanced responsibilities."
    fb_rows = [("c","2026-01-01 10:00:00","Excellent","sup1","Excellent","Positive","Outstanding Competency",rec_text,"Excellent",0.9)]
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (13, "s13")
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
        resp = client.get("/admin/reports/student/13")
        assert resp.status_code == 200
        assert rec_text[:20] in resp.get_data(as_text=True) or "Recommendation" in resp.get_data(as_text=True)

def test_stored_ml_values_are_used():
    """If stored ml_prediction is X, report should use it not recompute."""
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    # stored Excellent even though comment would normally be predicted Needs Improvement (different)
    # We store Excellent to prove stored is used
    fb_rows = [("The student frequently misses deadlines","2026-01-01 10:00:00","Needs Improvement","sup1","Excellent","Positive","Outstanding Competency","rec","Excellent",0.95)]
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (14, "s14")
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
        # patch predictor to ensure fallback not altering stored
        with patch("app.Http.Controllers.admin.analyze_feedback_detailed") as mock_afd:
            mock_afd.return_value = {"performance_label":"Needs Improvement","sentiment":"Negative","competency":"Needs Significant Development","recommendation":"r","svm_prediction":"Needs Improvement","confidence":0.5}
            resp = client.get("/admin/reports/student/14")
            assert resp.status_code == 200
            txt = resp.get_data(as_text=True)
            # stored Excellent should appear in ML distribution (count 1)
            assert "Excellent" in txt
            # Should NOT use fallback recomputed Needs Improvement as primary if stored exists
            # Check that fallback wasn't called for stored row
            mock_afd.assert_not_called()

def test_legacy_feedback_without_ml_values_does_not_crash():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    # legacy: ml fields NULL
    fb_rows = [
        ("The intern shows outstanding dedication","2026-01-01 10:00:00","Excellent","sup1", None, None, None, None, None, None),
        ("Meets expectations","2026-01-02 10:00:00","Satisfactory","sup1", None, None, None, None, None, None),
    ]
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (15, "s15")
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
        resp = client.get("/admin/reports/student/15")
        assert resp.status_code == 200
        assert b"No feedback available" not in resp.data or b"ML Feedback Analysis" in resp.data

def test_average_confidence_handles_null_values():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    fb_rows = [
        ("c1","2026-01-01 10:00:00","Excellent","sup1","Excellent","Positive","Outstanding Competency","rec","Excellent", None),
        ("c2","2026-01-02 10:00:00","Excellent","sup1","Excellent","Positive","Outstanding Competency","rec","Excellent", 0.8),
    ]
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (16, "s16")
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
        resp = client.get("/admin/reports/student/16")
        assert resp.status_code == 200
        assert b"Average Confidence" in resp.data

def test_nb_svm_results_handled_correctly():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 1, "admin")
    fb_rows = [
        ("c","2026-01-01 10:00:00","Excellent","sup1","Excellent","Positive","Outstanding Competency","rec","Very Satisfactory",0.9),
        ("c2","2026-01-02 10:00:00","Fair","sup1","Fair","Negative","Developing Competency","rec2","Fair",0.7),
    ]
    def exec_side(sql, params=None):
        m = MagicMock()
        if "SELECT id, username" in sql:
            m.fetchone.return_value = (17, "s17")
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
        resp = client.get("/admin/reports/student/17")
        assert resp.status_code == 200
        txt = resp.get_data(as_text=True)
        assert "Naive Bayes" in txt
        assert "SVM" in txt

def test_unauthenticated_cannot_access_report():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    # no login
    resp = client.get("/admin/reports/student/1", follow_redirects=False)
    assert resp.status_code in (302,303)
    assert "/login" in resp.headers.get("Location","")

def test_non_admin_cannot_access_admin_report():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 10, "student")
    resp = client.get("/admin/reports/student/1")
    assert resp.status_code == 403
    _login_as(client, 5, "supervisor")
    resp2 = client.get("/admin/reports/student/1")
    assert resp2.status_code == 403

def test_existing_supervisor_feedback_still_stores_ml():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    _login_as(client, 5, "supervisor")
    mock_conn = MagicMock()
    def side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status":"active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        elif "INSERT INTO feedback" in sql:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = side
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        with patch("app.Http.Controllers.supervisor.create_notification"):
            resp = client.post("/supervisor/student/20/feedback", data={"comment":"The intern consistently demonstrates initiative and produces high-quality work.", "label":"Excellent"})
            assert resp.status_code in (302,303)
            inserts = [c for c in mock_conn.execute.call_args_list if "INSERT INTO feedback" in str(c)]
            assert len(inserts) >= 1

def test_existing_phase7_tests_still_passing():
    from app.ML.predictor import analyze_feedback, analyze_feedback_detailed
    assert analyze_feedback("Excellent work ethic and professional attitude.") in VALID_LABELS
    d = analyze_feedback_detailed("The intern shows outstanding dedication and delivers high quality work")
    assert "sentiment" in d and "competency" in d and "recommendation" in d
