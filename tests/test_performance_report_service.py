import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.Services.performance_report_service import build_student_report
from app.ML.predictor import analyze_feedback_detailed
from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password


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
                cur.execute("DELETE FROM classroom_submissions WHERE student_id = ?", (sid,))
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


# ------------------ Service tests ------------------

def test_complete_student_report():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_rep_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_rep_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("Complete Rep", "A", sup, f"NXR-CR{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    a2 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A2", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 92, 100, 92, "manual"))
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a2, stu, 88, 100, 88, "imported"))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid, feedback_text="The student shows exceptional dedication and excellent teamwork")
    assert report["student"]["id"] == stu
    assert report["class"]["id"] == cid
    assert report["supervisor"]["id"] == sup
    assert report["overall_percentage"] == 90.0
    assert report["graded_count"] == 2
    assert report["total_count"] == 2
    assert report["completion_rate"] == 100.0
    assert report["performance_label"] == "Excellent"
    assert report["has_feedback"] is True
    assert report["sentiment"] in {"Positive", "Neutral", "Negative"}
    assert report["competency"]
    assert report["recommendation"]
    assert report["priority"] in {"low", "medium", "high", "critical"}
    assert report["strongest"] is not None
    assert report["weakest"] is not None
    assert len(report["assignments"]) == 2
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM classwork_scores WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id=?)", (cid,))
        cur.execute("DELETE FROM classroom_assignments WHERE classroom_id=?", (cid,))
        cur.execute("DELETE FROM classroom_students WHERE classroom_id=?", (cid,))
        cur.execute("DELETE FROM classrooms WHERE id=?", (cid,))
        cur.execute("DELETE FROM users WHERE id IN (?,?)", (sup, stu))
        conn.commit()
    finally:
        conn.close()


def test_numeric_only_report():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_num_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_num_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("NumOnly", "A", sup, f"NXR-NO{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 75, 100, 75, "manual"))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid, feedback_text="")
    assert report["has_feedback"] is False
    assert report["overall_percentage"] == 75.0
    assert report["performance_label"] == "Satisfactory"
    assert report["recommendation"]
    assert "targeted practice" in report["recommendation"].lower()


def test_feedback_report():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_fb_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_fb_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("FB Rep", "A", sup, f"NXR-FB{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 80, 100, 80, "manual"))
    conn.execute("INSERT INTO feedback (student_id,supervisor_id,comment) VALUES (?,?,?)", (stu, sup, "The student shows exceptional dedication to learning new skills and applies feedback effectively to improve performance."))
    conn.commit()
    conn.close()
    # build without explicit feedback_text will fetch latest feedback
    report = build_student_report(stu, cid)
    assert report["has_feedback"] is True
    assert report["sentiment"] == "Positive"
    assert "Outstanding Competency" in (report["competency"] or "")
    assert report["feedback_analysis"] is not None
    # cleanup
    _cleanup([sup], [stu], [cid])


def test_no_assignments():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_noa_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_noa_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("NoAssign", "A", sup, f"NXR-NA{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid)
    assert report["total_count"] == 0
    assert report["graded_count"] == 0
    assert report["overall_percentage"] is None
    assert report["completion_rate"] == 0.0
    assert report["assignments"] == []
    assert report["strongest"] is None
    assert report["weakest"] is None
    _cleanup([sup], [stu], [cid])


def test_no_grades():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_nog_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_nog_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("NoGrades", "A", sup, f"NXR-NG{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?)", (cid, sup, "A1", 100))
    conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?)", (cid, sup, "A2", 100))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid)
    assert report["total_count"] == 2
    assert report["graded_count"] == 0
    assert report["overall_percentage"] is None
    assert report["performance_label"] == "Satisfactory"
    assert report["assignments"][0]["graded"] is False
    _cleanup([sup], [stu], [cid])


def test_incomplete_assignments():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_inc_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_inc_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("Incomplete", "A", sup, f"NXR-IC{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A2", 100)).fetchone()
    conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A3", 100)).fetchone()
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 80, 100, 80, "manual"))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid)
    assert report["graded_count"] == 1
    assert report["total_count"] == 3
    assert report["completion_rate"] == 33.333333333333336 or round(report["completion_rate"], 1) == 33.3
    assert "incomplete work" in " ".join(report["basis"]).lower()
    assert report["strongest"]["title"] == "A1"
    _cleanup([sup], [stu], [cid])


def test_invalid_scores():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_inv_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_inv_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("Invalid", "A", sup, f"NXR-IV{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    # Insert valid but also test invalid handling via missing max_score etc - service should skip invalid
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 50, 100, 50, "manual"))
    # Try to insert invalid with 0 max_score — should be skipped in grade calc but still counted as row
    a2 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A2", 0)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a2, stu, 10, 0, 0, "manual"))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid)
    # Should not crash, should have valid overall based on valid scores
    assert report["graded_count"] == 1
    assert report["overall_percentage"] == 50.0
    # Invalid max_score entry should be ignored gracefully
    _cleanup([sup], [stu], [cid])


def test_missing_feedback():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_mf_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_mf_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("MissFB", "A", sup, f"NXR-MF{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 70, 100, 70, "manual"))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid, feedback_text="")
    assert report["has_feedback"] is False
    assert report["sentiment"] is None or report["sentiment"] == "Neutral" or report["sentiment"] == "Negative" or report["sentiment"] == "Positive"
    assert report["recommendation"]
    # basis should mention no feedback
    assert "no feedback" in " ".join(report["basis"]).lower()
    _cleanup([sup], [stu], [cid])


def test_recommendation_integration():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_rec_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_rec_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("RecInt", "A", sup, f"NXR-RI{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 92, 100, 92, "manual"))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid)
    assert report["ml_recommendation"]["performance_label"] == "Excellent"
    assert "maintaining performance" in report["recommendation"].lower()
    assert report["priority"] == "low"
    assert report["ml_recommendation"]["priority"] == "low"
    _cleanup([sup], [stu], [cid])


def test_classification_integration():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_cls_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_cls_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("ClsInt", "A", sup, f"NXR-CL{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 58, 100, 58, "manual"))
    conn.commit()
    conn.close()
    report = build_student_report(stu, cid)
    assert report["performance_label"] == "Needs Improvement"
    assert report["priority"] == "critical"
    assert "immediate targeted support" in report["recommendation"].lower()
    _cleanup([sup], [stu], [cid])


# ------------------ Integration: HTTP ------------------

def test_supervisor_report_access():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_sra_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_sra_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("SRA", "A", sup, f"NXR-SR{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 85, 100, 85, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup, "supervisor")
    resp = client.get(f"/supervisor/classes/{cid}/reports")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Performance Reports" in body
    assert "85.0%" in body or "85" in body
    assert "Very Satisfactory" in body
    _cleanup([sup], [stu], [cid])


def test_supervisor_ownership_enforcement():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup_owner = _create_user(conn, f"sup_own_{uid}", "supervisor")
    sup_other = _create_user(conn, f"sup_oth_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_own_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("OwnEnf", "A", sup_owner, f"NXR-OE{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup_other, "supervisor")
    assert client.get(f"/supervisor/classes/{cid}/reports").status_code == 404
    assert client.get(f"/supervisor/classes/{cid}/reports/{stu}").status_code == 404
    assert client.get(f"/supervisor/classes/{cid}/reports/export.csv").status_code == 404
    _cleanup([sup_owner, sup_other], [stu], [cid])


def test_supervisor_individual_student_report():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_ind_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_ind_{uid}", "student")
    stu2 = _create_user(conn, f"stu_ind2_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("IndRep", "A", sup, f"NXR-IR{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 92, 100, 92, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup, "supervisor")
    resp = client.get(f"/supervisor/classes/{cid}/reports/{stu}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "PERFORMANCE SUMMARY" in body
    assert "ML ANALYSIS" in body
    assert "RECOMMENDATION" in body
    assert "ACADEMIC PERFORMANCE" in body
    assert "92.0%" in body
    assert "Excellent" in body
    # student not in class should 404
    assert client.get(f"/supervisor/classes/{cid}/reports/{stu2}").status_code == 404
    _cleanup([sup], [stu, stu2], [cid])


def test_student_report_access():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_stuacc_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_stuacc_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("StuAcc", "A", sup, f"NXR-SA{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 75, 100, 75, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, stu, "student")
    resp = client.get(f"/student/classes/{cid}/reports")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Performance Report" in body or "PERFORMANCE SUMMARY" in body
    assert "75.0%" in body
    assert "Satisfactory" in body
    _cleanup([sup], [stu], [cid])


def test_student_cannot_view_another_student():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_nview_{uid}", "supervisor")
    stu_a = _create_user(conn, f"stu_a_{uid}", "student")
    stu_b = _create_user(conn, f"stu_b_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("NView", "A", sup, f"NXR-NV{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu_a))
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu_b))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu_a, 90, 100, 90, "manual"))
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu_b, 50, 100, 50, "manual"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, stu_a, "student")
    resp = client.get(f"/student/classes/{cid}/reports")
    body = resp.get_data(as_text=True)
    assert "90.0%" in body
    assert "50.0%" not in body  # should not see B's data
    # attempt IDOR via query params
    resp2 = client.get(f"/student/classes/{cid}/reports?student_id={stu_b}")
    assert resp2.status_code == 200
    assert "90.0%" in resp2.get_data(as_text=True)
    assert "50.0%" not in resp2.get_data(as_text=True)
    # attempt supervisor report as student should be 403
    assert client.get(f"/supervisor/classes/{cid}/reports").status_code == 403
    _cleanup([sup], [stu_a, stu_b], [cid])


def test_csv_export_authorization_and_content():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_csv_{uid}", "supervisor")
    sup_other = _create_user(conn, f"sup_csv2_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_csv_{uid}", "student")
    conn.commit()
    cid = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("CSVRep", "A", sup, f"NXR-CS{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid, stu))
    a1 = conn.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (cid, sup, "A1", 100)).fetchone()[0]
    conn.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, stu, 88, 100, 88, "imported"))
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, sup_other, "supervisor")
    assert client.get(f"/supervisor/classes/{cid}/reports/export.csv").status_code == 404
    _login_as(client, stu, "student")
    assert client.get(f"/supervisor/classes/{cid}/reports/export.csv").status_code == 403
    _login_as(client, sup, "supervisor")
    resp = client.get(f"/supervisor/classes/{cid}/reports/export.csv")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in resp.headers["Content-Disposition"]
    body = resp.get_data(as_text=True)
    # BOM check (first char is BOM when decoded)
    assert body.startswith("\ufeff") or "Student Number" in body
    assert "Student Number" in body
    assert "Overall %" in body
    assert "Performance" in body
    assert "Recommendation" in body
    assert "Priority" in body
    # Content should contain student's data
    assert "88.0" in body
    assert "Very Satisfactory" in body or "Satisfactory" in body
    _cleanup([sup, sup_other], [stu], [cid])


def test_cross_class_report_access_denied():
    uid = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    sup = _create_user(conn, f"sup_cross_{uid}", "supervisor")
    stu = _create_user(conn, f"stu_cross_{uid}", "student")
    conn.commit()
    cid1 = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("Cross1", "A", sup, f"NXR-C11{uid.upper()}", 0)).fetchone()[0]
    cid2 = conn.execute("INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id", ("Cross2", "A", sup, f"NXR-C22{uid.upper()}", 0)).fetchone()[0]
    conn.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (cid1, stu))
    # stu only in cid1, try to access cid2 report as student
    conn.commit()
    conn.close()
    client = app.test_client()
    _login_as(client, stu, "student")
    assert client.get(f"/student/classes/{cid2}/reports").status_code == 404
    _login_as(client, sup, "supervisor")
    # supervisor trying to view student from other class should 404
    assert client.get(f"/supervisor/classes/{cid2}/reports/{stu}").status_code == 404
    _cleanup([sup], [stu], [cid1, cid2])
