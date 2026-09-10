import uuid
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["role"] = role


def _create_user(conn, username, role):
    row = conn.execute(
        "INSERT INTO users (username,email,password,role,status) VALUES (?,?,?,?,?) RETURNING id",
        (username, f"{username}@example.com", hash_password("pass12345"), role, "active"),
    ).fetchone()
    return row[0]


def _cleanup_ids(sup_ids, stud_ids, class_ids):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for cid in class_ids:
            try:
                cur.execute("DELETE FROM classwork_scores WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (cid,))
                cur.execute("DELETE FROM classroom_assignment_meta WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (cid,))
                cur.execute("DELETE FROM classroom_assignments WHERE classroom_id = ?", (cid,))
                cur.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (cid,))
                cur.execute("DELETE FROM classrooms WHERE id = ?", (cid,))
            except Exception:
                pass
        for fid in stud_ids:
            try:
                cur.execute("DELETE FROM feedback WHERE student_id = ?", (fid,))
                cur.execute("DELETE FROM classroom_submissions WHERE student_id = ?", (fid,))
            except Exception:
                pass
        for uid in list(sup_ids) + list(stud_ids):
            try:
                cur.execute("DELETE FROM users WHERE id = ?", (uid,))
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------
# Supervisor authorization
# ------------------------------------------------------------------
def test_supervisor_insights_requires_owner():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_ins1_{uid}", "supervisor")
    other_sup = _create_user(conn, f"sup_ins_other_{uid}", "supervisor")
    student = _create_user(conn, f"stu_ins1_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights Owner", "A", sup, f"NXR-IO{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    conn.commit()
    conn.close()
    client = app.test_client()
    try:
        _login_as(client, other_sup, "supervisor")
        resp = client.get(f"/supervisor/classes/{classroom}/insights")
        assert resp.status_code == 404, "other supervisor should get 404"
        _login_as(client, student, "student")
        resp2 = client.get(f"/supervisor/classes/{classroom}/insights")
        assert resp2.status_code == 403, "student should be forbidden from supervisor insights"
        _login_as(client, sup, "supervisor")
        resp3 = client.get(f"/supervisor/classes/{classroom}/insights")
        assert resp3.status_code == 200
        body = resp3.get_data(as_text=True)
        assert "Performance Insights" in body
        assert "ML Insights" in body
    finally:
        _cleanup_ids([sup, other_sup], [student], [classroom])


def test_supervisor_insights_alias_routes():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_ins_alias_{uid}", "supervisor")
    student = _create_user(conn, f"stu_ins_alias_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights Alias", "A", sup, f"NXR-IA{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup, "supervisor")
    try:
        for path in [f"/supervisor/classes/{classroom}/insights", f"/supervisor/classes/{classroom}/ml-insights", f"/supervisor/classes/{classroom}/performance"]:
            resp = client.get(path)
            assert resp.status_code == 200, path
    finally:
        _cleanup_ids([sup], [student], [classroom])


# ------------------------------------------------------------------
# Student authorization
# ------------------------------------------------------------------
def test_student_insights_requires_membership():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_stu1_{uid}", "supervisor")
    student = _create_user(conn, f"stu_stu1_{uid}", "student")
    other_student = _create_user(conn, f"stu_other1_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights StuAuth", "A", sup, f"NXR-SA{uid.upper()}", 0),
    ).fetchone()[0]
    # only student is enrolled, other_student not
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    conn.commit()
    conn.close()
    client = app.test_client()
    try:
        _login_as(client, other_student, "student")
        resp = client.get(f"/student/classes/{classroom}/insights")
        assert resp.status_code == 404
        _login_as(client, sup, "supervisor")
        resp2 = client.get(f"/student/classes/{classroom}/insights")
        assert resp2.status_code == 403  # supervisor cannot access student insights (role mismatch)
        _login_as(client, student, "student")
        resp3 = client.get(f"/student/classes/{classroom}/insights")
        assert resp3.status_code == 200
        assert "Performance Insights" in resp3.get_data(as_text=True)
    finally:
        _cleanup_ids([sup], [student, other_student], [classroom])


def test_student_cannot_view_another_students_insights():
    """Student endpoint must never allow requesting another student's data via URL param."""
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_stu2_{uid}", "supervisor")
    student_a = _create_user(conn, f"stu_a_{uid}", "student")
    student_b = _create_user(conn, f"stu_b_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights Iso", "A", sup, f"NXR-IS{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student_a))
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student_b))
    # give different scores so averages differ
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student_a, 90, 100, 90, "manual"))
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student_b, 50, 100, 50, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    try:
        _login_as(client, student_a, "student")
        resp = client.get(f"/student/classes/{classroom}/insights")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        # Should show own average 90, not 50
        assert "90.0%" in body or "90" in body
        # Should not contain other student's average as own? At least ensure isolation via not showing both
        # Attempt to cheat via query param should still show own data
        resp2 = client.get(f"/student/classes/{classroom}/insights?student_id={student_b}")
        body2 = resp2.get_data(as_text=True)
        assert resp2.status_code == 200
        assert "90.0%" in body2  # still own, not b's 50
        # Also try a non-existent supervisor insights style param
        resp3 = client.get(f"/student/classes/{classroom}/insights?user_id={student_b}")
        assert resp3.status_code == 200
        assert "90.0%" in resp3.get_data(as_text=True)
    finally:
        _cleanup_ids([sup], [student_a, student_b], [classroom])


# ------------------------------------------------------------------
# Correct student feature data + performance label
# ------------------------------------------------------------------
def test_supervisor_insights_correct_feature_data_and_label():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_feat_{uid}", "supervisor")
    student = _create_user(conn, f"stu_feat_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights Feature", "A", sup, f"NXR-IF{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    # 3 assignments, 2 graded
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "Quiz", 10)).fetchone()[0]
    a2 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "Project", 20)).fetchone()[0]
    a3 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "Missing", 30)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 9, 10, 90, "manual"))
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a2, student, 16, 20, 80, "imported"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup, "supervisor")
    try:
        resp = client.get(f"/supervisor/classes/{classroom}/insights")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        # Check required fields
        assert "Average percentage" in body
        assert "Minimum percentage" in body
        assert "Maximum percentage" in body
        assert "Graded assignments / total assignments" in body
        assert "Completion rate" in body
        assert "Manual grades count" in body
        assert "Imported grades count" in body
        assert "Numeric performance label" in body
        # Verify actual values: average 85 -> Very Satisfactory, min 80, max 90, graded 2/3, completion 66.7, manual 1 imported 1
        assert "85.0%" in body or "85" in body
        assert "80.0%" in body or "80" in body
        assert "90.0%" in body or "90" in body
        assert "2 / 3" in body
        assert "66.7%" in body or "66.6%" in body
        assert "Very Satisfactory" in body
        # Check student name present
        assert f"stu_feat_{uid}" in body
    finally:
        _cleanup_ids([sup], [student], [classroom])


def test_student_insights_performance_label_variants():
    # Test Excellent threshold via 92% average
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_label_{uid}", "supervisor")
    student = _create_user(conn, f"stu_label_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights Label", "A", sup, f"NXR-IL{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 92, 100, 92, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, student, "student")
    try:
        resp = client.get(f"/student/classes/{classroom}/insights")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Excellent" in body
        assert "Average percentage" in body
        assert "92.0%" in body
    finally:
        _cleanup_ids([sup], [student], [classroom])


# ------------------------------------------------------------------
# Feedback ML analysis integration
# ------------------------------------------------------------------
def test_supervisor_insights_feedback_ml_when_available():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_fb_{uid}", "supervisor")
    student = _create_user(conn, f"stu_fb_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights FB", "A", sup, f"NXR-FB{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 85, 100, 85, "manual"))
    # Insert feedback with known excellent phrase
    comment = "The student shows exceptional dedication to learning new skills and applies feedback effectively to improve performance."
    conn.execute("INSERT INTO feedback (student_id,supervisor_id,comment,performance_label,created_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)", (student, sup, comment, "Excellent"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup, "supervisor")
    try:
        resp = client.get(f"/supervisor/classes/{classroom}/insights")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        # Should show feedback ML fields
        assert "sentiment" in body.lower()
        assert "competency" in body.lower()
        assert "recommendation" in body.lower()
        assert "confidence" in body.lower()
        assert "Naive Bayes prediction" in body
        assert "SVM prediction" in body
        # For excellent comment, expect Positive sentiment and Outstanding Competency somewhere
        assert "Positive" in body or "Outstanding Competency" in body
    finally:
        _cleanup_ids([sup], [student], [classroom])


def test_student_insights_feedback_ml_when_available():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_sfb_{uid}", "supervisor")
    student = _create_user(conn, f"stu_sfb_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights SFB", "A", sup, f"NXR-SF{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 75, 100, 75, "manual"))
    comment = "The student demonstrates solid technical skills and applies supervisor feedback appropriately."
    conn.execute("INSERT INTO feedback (student_id,supervisor_id,comment) VALUES (?,?,?)", (student, sup, comment))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, student, "student")
    try:
        resp = client.get(f"/student/classes/{classroom}/insights")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "sentiment" in body.lower()
        assert "competency" in body.lower()
        assert "Naive Bayes prediction" in body
        assert "SVM prediction" in body
    finally:
        _cleanup_ids([sup], [student], [classroom])


# ------------------------------------------------------------------
# Empty / no-score state
# ------------------------------------------------------------------
def test_supervisor_insights_empty_no_score_state():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_empty_{uid}", "supervisor")
    student = _create_user(conn, f"stu_empty_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights Empty", "A", sup, f"NXR-IE{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    # create assignment but no scores
    conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?)", (classroom, sup, "NoScore", 100))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup, "supervisor")
    try:
        resp = client.get(f"/supervisor/classes/{classroom}/insights")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        # Should handle None averages gracefully - shows — and Satisfactory label
        assert "—" in body or "Satisfactory" in body
        assert "0 / 1" in body
        assert "0.0%" in body
        # Should not crash and should mention no feedback
        assert "No feedback" in body or "No feedback data yet" in body or "sentiment" in body.lower()
    finally:
        _cleanup_ids([sup], [student], [classroom])


def test_student_insights_empty_no_score_state():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_sempty_{uid}", "supervisor")
    student = _create_user(conn, f"stu_sempty_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights SEmpty", "A", sup, f"NXR-SE{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    # No assignments at all - total_count 0
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, student, "student")
    try:
        resp = client.get(f"/student/classes/{classroom}/insights")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "—" in body or "Satisfactory" in body
        assert "0 / 0" in body
        assert "No graded assignments" in body or "No feedback" in body or "sentiment" in body.lower()
    finally:
        _cleanup_ids([sup], [student], [classroom])


def test_supervisor_insights_ui_entry_points_exist():
    """Verify entry points from gradebook/classroom workflows contain expected links."""
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_ui_{uid}", "supervisor")
    student = _create_user(conn, f"stu_ui_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Insights UI", "A", sup, f"NXR-UI{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup, "supervisor")
    try:
        resp = client.get(f"/supervisor/classes/{classroom}/gradebook")
        assert "Performance Insights" in resp.get_data(as_text=True) or "ML Insights" in resp.get_data(as_text=True)
        resp2 = client.get(f"/supervisor/classes/{classroom}")
        body2 = resp2.get_data(as_text=True)
        assert "Performance Insights" in body2 or "ML Insights" in body2
        assert f"/supervisor/classes/{classroom}/insights" in body2
        _login_as(client, student, "student")
        resp3 = client.get(f"/student/classes/{classroom}/gradebook")
        assert "Performance Insights" in resp3.get_data(as_text=True) or "ML Insights" in resp3.get_data(as_text=True)
        resp4 = client.get(f"/student/classes/{classroom}")
        assert "Performance Insights" in resp4.get_data(as_text=True) or "ML Insights" in resp4.get_data(as_text=True)
    finally:
        _cleanup_ids([sup], [student], [classroom])
