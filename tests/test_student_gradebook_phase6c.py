import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password

SUPERVISOR_ID = 99301
OTHER_STUDENT_ID = 99302
STUDENT_ID = 99303
CLASS_ID = 99301
OTHER_CLASS_ID = 99302


def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["role"] = role


def _setup():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for cid in (CLASS_ID, OTHER_CLASS_ID):
            cur.execute("DELETE FROM classwork_scores WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (cid,))
            cur.execute("DELETE FROM classroom_assignment_meta WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (cid,))
            cur.execute("DELETE FROM classroom_assignments WHERE classroom_id = ?", (cid,))
            cur.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (cid,))
            cur.execute("DELETE FROM classrooms WHERE id = ?", (cid,))
        cur.execute("DELETE FROM users WHERE id IN (?, ?, ?)", (SUPERVISOR_ID, OTHER_STUDENT_ID, STUDENT_ID))

        for uid, username, role in [
            (SUPERVISOR_ID, "phase6c_sup", "supervisor"),
            (OTHER_STUDENT_ID, "phase6c_other", "student"),
            (STUDENT_ID, "phase6c_student", "student"),
        ]:
            cur.execute(
                "INSERT INTO users (id, username, email, password, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, username, f"{username}@test.com", hash_password("pass12345"), role, "active"),
            )

        for cid, name in [(CLASS_ID, "Phase 6C Gradebook"), (OTHER_CLASS_ID, "Other Class")]:
            cur.execute(
                """INSERT INTO classrooms (id, supervisor_id, name, section, description, code, archived)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (cid, SUPERVISOR_ID, name, "TEST", "", f"NXR-{cid}",),
            )
        cur.execute("INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)", (CLASS_ID, STUDENT_ID))
        cur.execute("INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)", (OTHER_CLASS_ID, OTHER_STUDENT_ID))

        ids = []
        for title, points in [("Quiz One", 10), ("Imported Exam", 40), ("Not Yet Graded", 50)]:
            cur.execute(
                """INSERT INTO classroom_assignments
                   (classroom_id, author_id, title, description, due_at, points)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (CLASS_ID, SUPERVISOR_ID, title, "", None, points),
            )
            ids.append(cur.execute("SELECT last_insert_rowid()" if hasattr(conn, "execute") else "SELECT id FROM classroom_assignments WHERE classroom_id = ? AND title = ? ORDER BY id DESC LIMIT 1", (CLASS_ID, title)).fetchone()[0] if False else cur.execute("SELECT id FROM classroom_assignments WHERE classroom_id = ? AND title = ? ORDER BY id DESC LIMIT 1", (CLASS_ID, title)).fetchone()[0])

        cur.execute("INSERT INTO classwork_scores (assignment_id, student_id, score, max_score, percentage, grading_method) VALUES (?, ?, ?, ?, ?, ?)", (ids[0], STUDENT_ID, 8, 10, 80, "manual"))
        cur.execute("INSERT INTO classwork_scores (assignment_id, student_id, score, max_score, percentage, grading_method) VALUES (?, ?, ?, ?, ?, ?)", (ids[1], STUDENT_ID, 30, 40, 75, "imported"))
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for cid in (CLASS_ID, OTHER_CLASS_ID):
            cur.execute("DELETE FROM classwork_scores WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (cid,))
            cur.execute("DELETE FROM classroom_assignment_meta WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (cid,))
            cur.execute("DELETE FROM classroom_assignments WHERE classroom_id = ?", (cid,))
            cur.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (cid,))
            cur.execute("DELETE FROM classrooms WHERE id = ?", (cid,))
        cur.execute("DELETE FROM users WHERE id IN (?, ?, ?)", (SUPERVISOR_ID, OTHER_STUDENT_ID, STUDENT_ID))
        conn.commit()
    finally:
        conn.close()


def test_student_gradebook_displays_scores_and_overall():
    _setup()
    try:
        client = app.test_client()
        _login_as(client, STUDENT_ID, "student")
        response = client.get(f"/student/classes/{CLASS_ID}/gradebook")
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Quiz One" in body
        assert "Imported Exam" in body
        assert "Not Yet Graded" in body
        assert "8 / 10" in body
        assert "30 / 40" in body
        assert "80.0%" in body
        assert "75.0%" in body
        assert "76.0%" in body
        assert "manual" in body.lower()
        assert "imported" in body.lower()
        assert "—" in body
    finally:
        _cleanup()


def test_student_gradebook_requires_membership():
    _setup()
    try:
        client = app.test_client()
        _login_as(client, OTHER_STUDENT_ID, "student")
        response = client.get(f"/student/classes/{CLASS_ID}/gradebook")
        assert response.status_code == 404
    finally:
        _cleanup()
