import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.ML.predictor import analyze_feedback_detailed
from app.Services.ml_recommendation_service import (
    build_recommendation,
    build_recommendation_from_features,
)
from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password


def _features_for_avg(avg, graded=3, total=5, min_pct=None, max_pct=None, completion=None):
    if completion is None and total:
        completion = graded / total * 100 if total else 0.0
    return {
        "average_percentage": avg,
        "min_percentage": min_pct if min_pct is not None else (avg - 5 if avg is not None else None),
        "max_percentage": max_pct if max_pct is not None else (avg + 5 if avg is not None else None),
        "graded_count": graded,
        "total_count": total,
        "completion_rate": completion if completion is not None else 0.0,
        "manual_count": 1,
        "imported_count": 1,
    }


def test_excellent_recommendation():
    f = _features_for_avg(92)
    fa = analyze_feedback_detailed("")
    rec = build_recommendation_from_features(f, fa, performance_label="Excellent")
    assert rec["performance_label"] == "Excellent"
    assert rec["priority"] == "low"
    text = rec["recommendation"].lower()
    assert "maintaining performance" in text
    assert "advanced/challenging" in text or ("advanced" in text and "challenging" in text)
    assert "peer support" in text or "peer" in text
    assert "leadership" in text


def test_very_satisfactory_recommendation():
    f = _features_for_avg(87)
    fa = analyze_feedback_detailed("")
    rec = build_recommendation_from_features(f, fa, performance_label="Very Satisfactory")
    assert rec["performance_label"] == "Very Satisfactory"
    assert rec["priority"] == "low"
    text = rec["recommendation"].lower()
    assert "maintaining consistency" in text or "maintain consistency" in text
    assert "weaker areas" in text or "weaker" in text


def test_satisfactory_recommendation():
    f = _features_for_avg(78)
    fa = analyze_feedback_detailed("")
    rec = build_recommendation_from_features(f, fa, performance_label="Satisfactory")
    assert rec["performance_label"] == "Satisfactory"
    assert rec["priority"] == "medium"
    text = rec["recommendation"].lower()
    assert "targeted practice" in text
    assert "lower-scoring" in text or "lower" in text


def test_fair_recommendation():
    f = _features_for_avg(65)
    fa = analyze_feedback_detailed("")
    rec = build_recommendation_from_features(f, fa, performance_label="Fair")
    assert rec["performance_label"] == "Fair"
    assert rec["priority"] == "high"
    text = rec["recommendation"].lower()
    assert "focused remediation" in text
    assert "missed" in text or "weak" in text
    assert "supervisor guidance" in text


def test_needs_improvement_recommendation():
    f = _features_for_avg(45)
    fa = analyze_feedback_detailed("")
    rec = build_recommendation_from_features(f, fa, performance_label="Needs Improvement")
    assert rec["performance_label"] == "Needs Improvement"
    assert rec["priority"] == "critical"
    text = rec["recommendation"].lower()
    assert "immediate targeted support" in text
    assert "reviewing fundamentals" in text or "fundamentals" in text
    assert "missing" in text
    assert "supervisor" in text


def test_numeric_only_recommendation():
    # No feedback, only numeric gradebook data
    f = _features_for_avg(85, graded=2, total=4, min_pct=80, max_pct=90)
    fa = analyze_feedback_detailed("")
    assert fa["is_empty"] is True
    rec = build_recommendation_from_features(f, fa)
    assert rec["overall_percentage"] == 85
    assert rec["completion_rate"] == 50.0
    assert rec["graded_count"] == 2
    assert rec["total_count"] == 4
    assert "performance_label" in rec
    assert "recommendation" in rec
    assert "priority" in rec
    assert "basis" in rec
    # basis should mention gradebook and no feedback
    basis_text = " ".join(rec["basis"]).lower()
    assert "gradebook" in basis_text
    assert "no feedback" in basis_text
    assert not rec["has_feedback"]


def test_feedback_based_recommendation():
    f = _features_for_avg(78)
    fa = analyze_feedback_detailed("The student shows exceptional dedication and excellent teamwork")
    assert fa["is_empty"] is False
    rec = build_recommendation_from_features(f, fa, performance_label="Satisfactory")
    assert rec["has_feedback"] is True
    assert rec["feedback_label"] in {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}
    basis_text = " ".join(rec["basis"]).lower()
    assert "feedback ml classification" in basis_text


def test_missing_feedback():
    f = _features_for_avg(70)
    fa = analyze_feedback_detailed("")
    rec = build_recommendation_from_features(f, fa)
    assert rec["has_feedback"] is False
    # recommendation should still be valid and deterministic
    assert rec["recommendation"]
    assert rec["priority"] in {"low", "medium", "high", "critical"}


def test_missing_grades():
    # No assignments, no grades
    f = {
        "average_percentage": None,
        "min_percentage": None,
        "max_percentage": None,
        "graded_count": 0,
        "total_count": 0,
        "completion_rate": 0.0,
        "manual_count": 0,
        "imported_count": 0,
    }
    fa = analyze_feedback_detailed("")
    rec = build_recommendation_from_features(f, fa)
    assert rec["overall_percentage"] is None
    assert rec["graded_count"] == 0
    assert rec["total_count"] == 0
    assert rec["performance_label"] == "Satisfactory"  # None maps to Satisfactory
    assert rec["recommendation"]
    # Should mention no assignments or no grades
    assert "no assignments" in rec["recommendation"].lower() or "no grades" in rec["recommendation"].lower()


def test_incomplete_work():
    f = _features_for_avg(75, graded=1, total=3, min_pct=75, max_pct=75, completion=33.3)
    fa = analyze_feedback_detailed("")
    rec = build_recommendation_from_features(f, fa, performance_label="Satisfactory")
    assert rec["completion_rate"] == 33.3
    assert "incomplete work" in " ".join(rec["basis"]).lower()
    assert "missing" in rec["recommendation"].lower() or "completion" in rec["recommendation"].lower()


def test_invalid_data_handling():
    # Pass None features and invalid feedback
    rec = build_recommendation_from_features(None, None)
    assert rec["performance_label"] in {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}
    assert "recommendation" in rec
    assert "priority" in rec
    assert "basis" in rec
    # Invalid numeric values
    f_invalid = {
        "average_percentage": "not-a-number",
        "min_percentage": "bad",
        "max_percentage": None,
        "graded_count": "x",
        "total_count": "y",
        "completion_rate": "invalid",
        "manual_count": None,
        "imported_count": None,
    }
    rec2 = build_recommendation_from_features(f_invalid, analyze_feedback_detailed(""))
    assert rec2["recommendation"]
    # build_recommendation with invalid ids should not raise
    rec3 = build_recommendation(999999, 999999, feedback_text=None)
    assert rec3["performance_label"]
    assert rec3["recommendation"]


def test_recommendation_output_structure():
    f = _features_for_avg(88, graded=4, total=5, min_pct=80, max_pct=95)
    fa = analyze_feedback_detailed("Good job, meets expectations")
    rec = build_recommendation_from_features(f, fa, performance_label="Very Satisfactory")
    # Must contain structured keys per spec
    for key in ("performance_label", "overall_percentage", "completion_rate", "recommendation", "priority", "basis"):
        assert key in rec, f"missing key {key}"
    assert isinstance(rec["basis"], list)
    assert isinstance(rec["recommendation"], str)
    assert rec["priority"] in {"low", "medium", "high", "critical"}


def test_recommendation_uses_existing_predictor_not_duplicate():
    # Ensure service reuses predictor by checking that feedback analysis is from predictor
    f = _features_for_avg(75)
    feedback_text = "The student demonstrates outstanding dedication and excellent teamwork"
    fa = analyze_feedback_detailed(feedback_text)
    rec = build_recommendation_from_features(f, fa)
    # feedback_label should match predictor's performance_label
    assert rec["feedback_label"] == fa["performance_label"]
    assert rec["sentiment"] == fa["sentiment"]


# ------------------------------------------------------------------
# Integration: ensure insights pages expose recommendation and authorization
# ------------------------------------------------------------------
def _create_user(conn, username, role):
    row = conn.execute(
        "INSERT INTO users (username,email,password,role,status) VALUES (?,?,?,?,?) RETURNING id",
        (username, f"{username}@example.com", hash_password("pass12345"), role, "active"),
    ).fetchone()
    return row[0]


def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["role"] = role


def _cleanup(sup_ids, stu_ids, class_ids):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for cid in class_ids:
            try:
                cur.execute("DELETE FROM classwork_scores WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (cid,))
                cur.execute("DELETE FROM classroom_assignments WHERE classroom_id = ?", (cid,))
                cur.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (cid,))
                cur.execute("DELETE FROM classrooms WHERE id = ?", (cid,))
            except Exception:
                pass
        for sid in stu_ids:
            try:
                cur.execute("DELETE FROM feedback WHERE student_id = ?", (sid,))
            except Exception:
                pass
        for uid in list(sup_ids) + list(stu_ids):
            try:
                cur.execute("DELETE FROM users WHERE id = ?", (uid,))
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


def test_supervisor_insights_shows_recommendation():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_rec_{uid}", "supervisor")
    student = _create_user(conn, f"stu_rec_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Rec Class", "A", sup, f"NXR-RC{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 92, 100, 92, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup, "supervisor")
    try:
        resp = client.get(f"/supervisor/classes/{classroom}/insights")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Recommendation" in body
        assert "performance_label" in body
        assert "overall_percentage" in body.lower() or "overall" in body.lower()
        assert "priority" in body.lower()
        assert "basis" in body.lower()
        assert "Excellent" in body
    finally:
        _cleanup([sup], [student], [classroom])


def test_student_insights_shows_recommendation():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_srec_{uid}", "supervisor")
    student = _create_user(conn, f"stu_srec_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("SRec Class", "A", sup, f"NXR-SR{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 58, 100, 58, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, student, "student")
    try:
        resp = client.get(f"/student/classes/{classroom}/insights")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Recommendation" in body or "ML Recommendation" in body
        assert "Needs Improvement" in body
        assert "priority" in body.lower()
    finally:
        _cleanup([sup], [student], [classroom])


def test_student_cannot_access_another_students_recommendation():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_iso_{uid}", "supervisor")
    stu_a = _create_user(conn, f"stu_a_{uid}", "student")
    stu_b = _create_user(conn, f"stu_b_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Iso Class", "A", sup, f"NXR-IS{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, stu_a))
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, stu_b))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu_a, 90, 100, 90, "manual"))
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu_b, 50, 100, 50, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, stu_a, "student")
    try:
        resp = client.get(f"/student/classes/{classroom}/insights")
        body = resp.get_data(as_text=True)
        assert "90.0%" in body or "90" in body
        # Trying to spoof via query param should still show own data
        resp2 = client.get(f"/student/classes/{classroom}/insights?student_id={stu_b}")
        body2 = resp2.get_data(as_text=True)
        assert "90.0%" in body2
        # Should not contain other student's recommendation disclosure beyond own
        # Supervisor endpoint should be forbidden for student
        resp3 = client.get(f"/supervisor/classes/{classroom}/insights")
        assert resp3.status_code == 403
    finally:
        _cleanup([sup], [stu_a, stu_b], [classroom])


def test_supervisor_ownership_enforcement_for_recommendation():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup_owner = _create_user(conn, f"sup_owner_{uid}", "supervisor")
    sup_other = _create_user(conn, f"sup_other_{uid}", "supervisor")
    student = _create_user(conn, f"stu_own_{uid}", "student")
    conn.commit()
    classroom = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Owner Class", "A", sup_owner, f"NXR-OW{uid.upper()}", 0),
    ).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup_other, "supervisor")
    try:
        resp = client.get(f"/supervisor/classes/{classroom}/insights")
        assert resp.status_code == 404
    finally:
        _cleanup([sup_owner, sup_other], [student], [classroom])
