import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password

def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["role"] = role

def _ensure_users():
    conn = get_db_connection()
    cur = conn.cursor()
    for uid, uname, role in [(99001, "test_sup_cla", "supervisor"), (99011, "test_stu_cla", "student")]:
        cur.execute("SELECT id FROM users WHERE id=?", (uid,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (id, username, email, password, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, uname, f"{uname}@test.com", hash_password("pass12345"), role, "active"),
            )
        else:
            cur.execute("UPDATE users SET status='active', role=? WHERE id=?", (role, uid))
    conn.commit()
    conn.close()

def _cleanup():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM classwork_scores WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id=99001))"
        )
        cur.execute(
            "DELETE FROM classwork_submission_files WHERE submission_id IN (SELECT id FROM classwork_submissions WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id=99001)))"
        )
        cur.execute(
            "DELETE FROM classwork_submissions WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id=99001))"
        )
        cur.execute("DELETE FROM classroom_assignments WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id=99001)")
        cur.execute("DELETE FROM classroom_students WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id=99001)")
        cur.execute("DELETE FROM classrooms WHERE supervisor_id=99001")
        conn.commit()
    except Exception:
        pass
    conn.close()


def _setup_classwork(points=100):
    # returns (cid, aid, sid)
    client = app.test_client()
    _login_as(client, 99001, "supervisor")
    client.post("/supervisor/classes/create", data={"class_name": "Test Class", "section": "A", "description": "desc"})
    conn = get_db_connection()
    row = conn.execute("SELECT id, code FROM classrooms WHERE supervisor_id=99001 ORDER BY id DESC LIMIT 1").fetchone()
    cid = row["id"] if "id" in row.keys() else row[0]
    code = row["code"] if "code" in row.keys() else row[1]
    conn.close()
    # join student
    client_s = app.test_client()
    _login_as(client_s, 99011, "student")
    client_s.post("/student/classes/join", data={"class_code": code})
    # create assignment
    _login_as(client, 99001, "supervisor")
    client.post(
        f"/supervisor/classes/{cid}/classwork",
        data={"title": "HW Test", "description": "desc", "points": str(points), "due_at": "", "activity_type": "assignment"},
    )
    conn = get_db_connection()
    a_row = conn.execute("SELECT id FROM classroom_assignments WHERE classroom_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    aid = a_row["id"] if "id" in a_row.keys() else a_row[0]
    # submission
    conn.execute(
        "INSERT INTO classwork_submissions (assignment_id, student_id, attempt_no, content, status) VALUES (?, ?, 1, 'test', 'submitted')",
        (aid, 99011),
    )
    conn.commit()
    sub = conn.execute(
        "SELECT id FROM classwork_submissions WHERE assignment_id=? AND student_id=? ORDER BY id DESC LIMIT 1", (aid, 99011)
    ).fetchone()
    sid = sub["id"] if "id" in sub.keys() else sub[0]
    conn.close()
    return cid, aid, sid


def test_manual_grade_creates_normalized_score():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    _ensure_users()
    _cleanup()
    cid, aid, sid = _setup_classwork(points=100)
    client = app.test_client()
    _login_as(client, 99001, "supervisor")
    resp = client.post(
        f"/supervisor/classes/{cid}/classwork/{aid}/submissions/{sid}/grade",
        data={"grade": "80", "feedback": "good", "action": "save"},
    )
    assert resp.status_code in (302, 303)
    conn = get_db_connection()
    row = conn.execute(
        "SELECT assignment_id, student_id, score, max_score, percentage, grading_method FROM classwork_scores WHERE assignment_id=? AND student_id=?",
        (aid, 99011),
    ).fetchone()
    assert row is not None
    assert int(row["assignment_id"] if "assignment_id" in row.keys() else row[0]) == aid
    assert int(row["student_id"] if "student_id" in row.keys() else row[1]) == 99011
    assert float(row["score"] if "score" in row.keys() else row[2]) == 80.0
    assert float(row["max_score"] if "max_score" in row.keys() else row[3]) == 100.0
    assert float(row["percentage"] if "percentage" in row.keys() else row[4]) == 80.0
    assert (row["grading_method"] if "grading_method" in row.keys() else row[5]) == "manual"
    # also verify submission updated
    sub = conn.execute("SELECT grade, status FROM classwork_submissions WHERE id=?", (sid,)).fetchone()
    assert sub is not None
    assert float(sub["grade"] if "grade" in sub.keys() else sub[0]) == 80
    conn.close()
    _cleanup()
    conn = get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()


def test_manual_regrade_updates_existing_score():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    _ensure_users()
    _cleanup()
    cid, aid, sid = _setup_classwork(points=100)
    client = app.test_client()
    _login_as(client, 99001, "supervisor")
    client.post(f"/supervisor/classes/{cid}/classwork/{aid}/submissions/{sid}/grade", data={"grade": "80", "feedback": "first", "action": "save"})
    client.post(f"/supervisor/classes/{cid}/classwork/{aid}/submissions/{sid}/grade", data={"grade": "90", "feedback": "second", "action": "save"})
    conn = get_db_connection()
    cnt = conn.execute("SELECT COUNT(*) FROM classwork_scores WHERE assignment_id=? AND student_id=?", (aid, 99011)).fetchone()[0]
    assert cnt == 1
    row = conn.execute("SELECT score, percentage FROM classwork_scores WHERE assignment_id=? AND student_id=?", (aid, 99011)).fetchone()
    assert float(row["score"] if "score" in row.keys() else row[0]) == 90.0
    assert float(row["percentage"] if "percentage" in row.keys() else row[1]) == 90.0
    conn.close()
    _cleanup()
    conn = get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()


def test_manual_grade_max_score_zero():
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    _ensure_users()
    _cleanup()
    cid, aid, sid = _setup_classwork(points=0)
    client = app.test_client()
    _login_as(client, 99001, "supervisor")
    resp = client.post(f"/supervisor/classes/{cid}/classwork/{aid}/submissions/{sid}/grade", data={"grade": "0", "feedback": "", "action": "save"})
    assert resp.status_code in (302, 303)
    conn = get_db_connection()
    row = conn.execute("SELECT percentage, max_score FROM classwork_scores WHERE assignment_id=? AND student_id=?", (aid, 99011)).fetchone()
    assert row is not None
    assert float(row["percentage"] if "percentage" in row.keys() else row[0]) == 0
    assert float(row["max_score"] if "max_score" in row.keys() else row[1]) == 0
    conn.close()
    _cleanup()
    conn = get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()
