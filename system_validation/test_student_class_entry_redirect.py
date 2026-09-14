import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password


def _login_as_student(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = "student"


def _create_user(conn, username, role):
    row = conn.execute(
        "INSERT INTO users (username,email,password,role,status) VALUES (?,?,?,?,?) RETURNING id",
        (username, f"{username}@example.com", hash_password("pass12345"), role, "active"),
    ).fetchone()
    return row[0]


def test_student_classes_directory_screen_is_removed():
    suffix = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    supervisor_id = _create_user(conn, f"sup_entry_{suffix}", "supervisor")
    student_id = _create_user(conn, f"stu_entry_{suffix}", "student")
    conn.commit()

    classroom_id = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Entry Redirect", "A", supervisor_id, f"NXR-ER{suffix.upper()}", 0),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)",
        (classroom_id, student_id),
    )
    conn.commit()
    conn.close()

    client = app.test_client()
    try:
        _login_as_student(client, student_id)

        response = client.get("/student/classes")
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert f"/student/classes/{classroom_id}" in body
        assert "window.location.replace" in body
        assert "Open Intern Classroom" not in body
        assert "+ Join Intern Classroom" not in body
        assert "Your internship classrooms and OJT workspaces" not in body

        conn = get_db_connection()
        conn.execute(
            "DELETE FROM classroom_students WHERE classroom_id = ? AND student_id = ?",
            (classroom_id, student_id),
        )
        conn.commit()
        conn.close()

        no_class_response = client.get("/student/classes")
        assert no_class_response.status_code == 200
        no_class_body = no_class_response.get_data(as_text=True)
        assert "/student/classes/join" in no_class_body
        assert "Open Intern Classroom" not in no_class_body
    finally:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classrooms WHERE id = ?", (classroom_id,))
            conn.execute(
                "DELETE FROM users WHERE id IN (?, ?)",
                (supervisor_id, student_id),
            )
            conn.commit()
        finally:
            conn.close()
