import pathlib
import sys
import uuid
from urllib.parse import parse_qs, urlsplit

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


def test_message_open_returns_to_same_origin_page_and_keeps_dashboard_fallback():
    suffix = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    supervisor_id = _create_user(conn, f"sup_chat_ctx_{suffix}", "supervisor")
    student_id = _create_user(conn, f"stu_chat_ctx_a_{suffix}", "student")
    classmate_id = _create_user(conn, f"stu_chat_ctx_b_{suffix}", "student")
    conn.commit()

    classroom_id = conn.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("Chat Context", "A", supervisor_id, f"NXR-CC{suffix.upper()}", 0),
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

        response = client.get(
            f"/messages/open/{classmate_id}",
            headers={
                "Referer": f"http://localhost/student/classes/{classroom_id}?tab=people"
            },
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)
        location = response.headers["Location"]
        parsed = urlsplit(location)
        query = parse_qs(parsed.query)
        assert parsed.path == f"/student/classes/{classroom_id}"
        assert query.get("tab") == ["people"]
        assert query.get("assistant") == ["messages"]
        assert query.get("contact") == [str(classmate_id)]
        assert "/student/dashboard" not in location

        fallback = client.get(
            f"/messages/open/{classmate_id}",
            headers={"Referer": "https://example.com/not-nexora"},
            follow_redirects=False,
        )
        assert fallback.status_code in (302, 303)
        fallback_location = fallback.headers["Location"]
        fallback_parsed = urlsplit(fallback_location)
        fallback_query = parse_qs(fallback_parsed.query)
        assert fallback_parsed.path == "/student/dashboard"
        assert fallback_query.get("assistant") == ["messages"]
        assert fallback_query.get("contact") == [str(classmate_id)]
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
