import csv
from io import StringIO

from app.Models.db import get_db_connection
from app.Services.password_security import hash_password


SUPERVISOR_ID = 99301
OTHER_SUPERVISOR_ID = 99302
STUDENT_ID = 99311
CLASS_ID = 99301


def _login(client, user_id, role="supervisor"):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["role"] = role


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
            (SUPERVISOR_ID, "phase6e_sup", "supervisor"),
            (OTHER_SUPERVISOR_ID, "phase6e_other", "supervisor"),
            (STUDENT_ID, "phase6e_student", "student"),
        ]:
            cur.execute(
                "INSERT INTO users (id, username, email, password, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, username, f"{username}@test.com", hash_password("pass12345"), role, "active"),
            )

        cur.execute(
            """INSERT INTO classrooms
               (id, supervisor_id, name, section, description, code, archived)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (CLASS_ID, SUPERVISOR_ID, "Export Class", "A", "", "NXR-6E001"),
        )
        conn.commit()
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


def test_supervisor_gradebook_export_requires_owner(client, db):
    _setup()
    try:
        _login(client, OTHER_SUPERVISOR_ID)
        response = client.get(f"/supervisor/classes/{CLASS_ID}/gradebook/export.csv")
        assert response.status_code == 404
    finally:
        _cleanup()


def test_supervisor_gradebook_export_csv_contains_scores_and_overall(client, db):
    _setup()
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)", (CLASS_ID, STUDENT_ID))
            a1 = cur.execute(
                "INSERT INTO classroom_assignments (classroom_id, author_id, title, description, due_at, points) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (CLASS_ID, SUPERVISOR_ID, "Quiz 1", "", None, 20),
            ).fetchone()[0]
            a2 = cur.execute(
                "INSERT INTO classroom_assignments (classroom_id, author_id, title, description, due_at, points) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (CLASS_ID, SUPERVISOR_ID, "Project", "", None, 50),
            ).fetchone()[0]
            cur.execute(
                "INSERT INTO classwork_scores (assignment_id, student_id, score, max_score, percentage, grading_method) VALUES (?, ?, ?, ?, ?, ?)",
                (a1, STUDENT_ID, 18, 20, 90, "manual"),
            )
            conn.commit()
        finally:
            conn.close()

        _login(client, SUPERVISOR_ID)
        response = client.get(f"/supervisor/classes/{CLASS_ID}/gradebook/export.csv")
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/csv")
        assert "attachment" in response.headers["Content-Disposition"]

        text = response.get_data(as_text=True).lstrip("\ufeff")
        rows = list(csv.reader(StringIO(text)))
        assert rows[0] == ["Student Number", "Student", "Email", "Quiz 1", "Project", "Overall %"]
        assert rows[1][1:3] == ["phase6e_student", "phase6e_student@test.com"]
        assert rows[1][3:] == ["18", "", "90.0"]
    finally:
        _cleanup()
