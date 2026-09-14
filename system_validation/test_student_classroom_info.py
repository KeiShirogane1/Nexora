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


def test_student_classroom_info_is_full_and_membership_protected():
    suffix = uuid.uuid4().hex[:6]
    conn = get_db_connection()
    supervisor_id = _create_user(conn, f"sup_info_{suffix}", "supervisor")
    student_id = _create_user(conn, f"stu_info_{suffix}", "student")
    outsider_id = _create_user(conn, f"stu_out_{suffix}", "student")
    conn.commit()

    classroom_id = conn.execute(
        """INSERT INTO classrooms
           (name,section,supervisor_id,code,classroom_type,archived)
           VALUES (?,?,?,?,?,?) RETURNING id""",
        ("Software Engineering Intern", "BSIT-4A", supervisor_id, f"NXR-I{suffix.upper()}", "internship", 0),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)",
        (classroom_id, student_id),
    )
    conn.execute(
        """INSERT INTO classroom_internship_details (
               classroom_id, internship_title, company_name, industry,
               work_arrangement, schedule_type, hours_mode, compensation,
               location, start_date, end_date, enrollment_deadline,
               required_hours, company_website, company_description,
               internship_description
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            classroom_id,
            "Software Engineering Intern",
            "Nexora Labs",
            "Information Technology",
            "Hybrid",
            "fixed_dates",
            "specified",
            "Paid",
            "Taguig City",
            "2026-09-01",
            "2026-12-15",
            "2026-08-20",
            486,
            "https://example.com",
            "A software development company.",
            "Build and maintain internship software projects.",
        ),
    )
    conn.execute(
        "INSERT INTO classroom_internship_responsibilities (classroom_id,responsibility,sort_order) VALUES (?,?,?)",
        (classroom_id, "Develop assigned features", 0),
    )
    conn.execute(
        "INSERT INTO classroom_internship_qualifications (classroom_id,qualification,sort_order) VALUES (?,?,?)",
        (classroom_id, "Basic Python knowledge", 0),
    )
    conn.commit()
    conn.close()

    client = app.test_client()
    try:
        _login_as_student(client, student_id)
        response = client.get(f"/student/classes/{classroom_id}/info")
        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        info = data["classroom"]
        assert info["internship_title"] == "Software Engineering Intern"
        assert info["company_name"] == "Nexora Labs"
        assert info["industry"] == "Information Technology"
        assert info["work_arrangement"] == "Hybrid"
        assert info["location"] == "Taguig City"
        assert info["schedule_type"] == "fixed_dates"
        assert info["hours_mode"] == "specified"
        assert info["required_hours"] == 486
        assert info["company_website"] == "https://example.com"
        assert info["responsibilities"] == ["Develop assigned features"]
        assert info["qualifications"] == ["Basic Python knowledge"]

        page = client.get(f"/student/classes/{classroom_id}")
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        assert "class-banner-menu-button" in body
        assert "Classroom Information" in body
        assert "Leave Intern Classroom" in body
        assert f"/student/classes/{classroom_id}/info" in body
        assert "Eligibility / Qualifications" in body

        _login_as_student(client, outsider_id)
        forbidden = client.get(f"/student/classes/{classroom_id}/info")
        assert forbidden.status_code == 404
    finally:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM classroom_internship_responsibilities WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classroom_internship_qualifications WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classroom_internship_details WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classrooms WHERE id = ?", (classroom_id,))
            conn.execute(
                "DELETE FROM users WHERE id IN (?, ?, ?)",
                (supervisor_id, student_id, outsider_id),
            )
            conn.commit()
        finally:
            conn.close()
