import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password


def _login_as(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role


def _create_user(conn, username, role):
    row = conn.execute(
        "INSERT INTO users (username,email,password,role,status) VALUES (?,?,?,?,?) RETURNING id",
        (username, f"{username}@example.com", hash_password("pass12345"), role, "active"),
    ).fetchone()
    return row[0]


def test_student_cannot_open_peer_ml_and_people_list_uses_chat():
    suffix = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    supervisor_id = _create_user(conn, f"sup_peer_priv_{suffix}", "supervisor")
    student_id = _create_user(conn, f"stu_peer_priv_a_{suffix}", "student")
    classmate_id = _create_user(conn, f"stu_peer_priv_b_{suffix}", "student")
    conn.commit()

    classroom_id = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Peer Privacy", "A", supervisor_id, f"NXR-PP{suffix.upper()}", 0),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)",
        (classroom_id, student_id),
    )
    conn.execute(
        "INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)",
        (classroom_id, classmate_id),
    )
    conn.commit()
    conn.close()

    client = app.test_client()
    try:
        _login_as(client, student_id, "student")

        peer_insights = client.get(
            f"/student/classes/{classroom_id}/people/{classmate_id}/insights"
        )
        assert peer_insights.status_code == 404

        own_insights = client.get(f"/student/classes/{classroom_id}/insights")
        assert own_insights.status_code == 200

        classroom_page = client.get(f"/student/classes/{classroom_id}")
        assert classroom_page.status_code == 200
        body = classroom_page.get_data(as_text=True)
        assert f"/student/classes/{classroom_id}/people/{classmate_id}/insights" not in body
        assert f"/messages/open/{classmate_id}" in body

        classmate_profile = client.get(
            f"/student/classes/{classroom_id}/people/{classmate_id}"
        )
        assert classmate_profile.status_code == 200
        assert "View ML Insights" not in classmate_profile.get_data(as_text=True)
    finally:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classrooms WHERE id = ?", (classroom_id,))
            conn.execute(
                "DELETE FROM users WHERE id IN (?, ?, ?)",
                (supervisor_id, student_id, classmate_id),
            )
            conn.commit()
        finally:
            conn.close()
