import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password


SUPERVISOR_ID = 99201
OTHER_SUPERVISOR_ID = 99202
STUDENT_ID = 99211
CLASS_ID = 99201


def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["role"] = role


def _setup():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM classwork_scores WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (CLASS_ID,))
        cur.execute("DELETE FROM classroom_assignment_meta WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (CLASS_ID,))
        cur.execute("DELETE FROM classroom_assignments WHERE classroom_id = ?", (CLASS_ID,))
        cur.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (CLASS_ID,))
        cur.execute("DELETE FROM classrooms WHERE id = ?", (CLASS_ID,))
        cur.execute("DELETE FROM users WHERE id IN (?, ?, ?)", (SUPERVISOR_ID, OTHER_SUPERVISOR_ID, STUDENT_ID))

        for uid, username, role in [
            (SUPERVISOR_ID, "phase6b_sup", "supervisor"),
            (OTHER_SUPERVISOR_ID, "phase6b_other", "supervisor"),
            (STUDENT_ID, "phase6b_student", "student"),
        ]:
            cur.execute(
                "INSERT INTO users (id, username, email, password, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, username, f"{username}@test.com", hash_password("pass12345"), role, "active"),
            )

        cur.execute(
            """INSERT INTO classrooms (id, supervisor_id, name, section, description, code, archived)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (CLASS_ID, SUPERVISOR_ID, "Phase 6B Gradebook", "TEST", "", "NXR-6BTEST",),
        )
        cur.execute(
            "INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)",
            (CLASS_ID, STUDENT_ID),
        )

        assignment_ids = []
        for title, points in [("Quiz One", 10), ("Project One", 20), ("Missing Work", 30)]:
            cur.execute(
                """INSERT INTO classroom_assignments
                   (classroom_id, author_id, title, description, due_at, points)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (CLASS_ID, SUPERVISOR_ID, title, "", None, points),
            )
            row = cur.execute(
                "SELECT id FROM classroom_assignments WHERE classroom_id = ? AND title = ? ORDER BY id DESC LIMIT 1",
                (CLASS_ID, title),
            ).fetchone()
            assignment_ids.append(row[0])

        cur.execute(
            """INSERT INTO classwork_scores
               (assignment_id, student_id, score, max_score, percentage, grading_method)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assignment_ids[0], STUDENT_ID, 8, 10, 80, "manual"),
        )
        cur.execute(
            """INSERT INTO classwork_scores
               (assignment_id, student_id, score, max_score, percentage, grading_method)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assignment_ids[1], STUDENT_ID, 15, 20, 75, "imported"),
        )
        conn.commit()
        return assignment_ids
    finally:
        conn.close()


def _cleanup():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM classwork_scores WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (CLASS_ID,))
        cur.execute("DELETE FROM classroom_assignment_meta WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id = ?)", (CLASS_ID,))
        cur.execute("DELETE FROM classroom_assignments WHERE classroom_id = ?", (CLASS_ID,))
        cur.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (CLASS_ID,))
        cur.execute("DELETE FROM classrooms WHERE id = ?", (CLASS_ID,))
        cur.execute("DELETE FROM users WHERE id IN (?, ?, ?)", (SUPERVISOR_ID, OTHER_SUPERVISOR_ID, STUDENT_ID))
        conn.commit()
    finally:
        conn.close()


def test_supervisor_gradebook_displays_normalized_scores_and_overall():
    _setup()
    try:
        client = app.test_client()
        _login_as(client, SUPERVISOR_ID, "supervisor")
        response = client.get(f"/supervisor/classes/{CLASS_ID}/gradebook")
        body = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "Quiz One" in body
        assert "Project One" in body
        assert "Missing Work" in body
        assert "8 / 10" in body
        assert "15 / 20" in body
        assert "manual" in body
        assert "imported" in body
        assert "76.7%" in body
        assert "2/3 graded" in body
        assert body.count("—") >= 1
    finally:
        _cleanup()


def test_supervisor_gradebook_rejects_other_supervisor():
    _setup()
    try:
        client = app.test_client()
        _login_as(client, OTHER_SUPERVISOR_ID, "supervisor")
        response = client.get(f"/supervisor/classes/{CLASS_ID}/gradebook")
        assert response.status_code == 404
    finally:
        _cleanup()
