import pathlib
import uuid
from unittest.mock import patch

from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password


ROOT = pathlib.Path(__file__).resolve().parent.parent


def _text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def _login_as_admin(client, user_id=99001):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = "admin"


def _create_user(conn, username, role):
    row = conn.execute(
        "INSERT INTO users (username,email,password,role,status) VALUES (?,?,?,?,?) RETURNING id",
        (username, f"{username}@example.com", hash_password("pass12345"), role, "active"),
    ).fetchone()
    return int(row[0])


def test_shared_close_copy_and_admin_cleanup_rules_exist():
    logout = _text("resources/views/components/logout_modal.html")
    admin_consistency = _text("resources/views/components/admin_consistency.html")

    assert "nx-global-close-copy-consistency" in logout
    assert ".nx-copy-username" in logout
    assert "background: transparent !important" in logout
    assert "#dc2626" in logout
    assert "#991b1b" in logout
    assert "removeDuplicateClassInfoMenuAction" in logout

    assert "removeAdminBackControls" in admin_consistency
    assert "actualProgramsFromDirectory" in admin_consistency
    assert "Other / Specify Program" in admin_consistency
    assert "'bsit': 'Bachelor of Science in Information Technology'" in admin_consistency


def test_admin_documents_match_supervisor_structure_without_type_filter():
    template = _text("resources/views/admin/student_documents.html")

    assert "components/supervisor_document_styles.html" in template
    assert "supervisor-doc-summary" in template
    assert "supervisor-doc-filter-grid" in template
    assert "supervisor-doc-classroom-card" in template
    assert 'name="documents"' in template
    assert 'name="type"' not in template
    assert "Back to Student Documents" not in template


def test_admin_document_folder_file_actions_and_full_student_information():
    template = _text("resources/views/admin/student_document_folder.html")
    controller = _text("app/Http/Controllers/admin_classrooms.py")

    assert "Open PDF" in template
    assert "Download TXT" in template
    assert "download=1" in template
    assert "Complete Student Information" in template
    for label in (
        "Phone Number",
        "Home Address",
        "Emergency Contact",
        "Relationship",
        "Emergency Phone",
        "Emergency Email",
    ):
        assert label in template

    assert 'as_attachment=request.args.get("download") == "1"' in controller
    assert "sp.emergency_relationship" in controller
    assert "sp.phone_number" in controller
    assert "sp.home_address" in controller


def test_admin_insights_and_classroom_detail_use_real_separate_evidence():
    insights = _text("resources/views/admin/student_insights.html")
    classroom = _text("resources/views/admin/classroom_detail.html")

    assert "admin-insights-kpis" in insights
    assert "ML Feedback Intelligence" in insights
    assert "Official OJT Evaluation" in insights
    assert "No combined OJT grade" in insights

    assert "Overall Insights" in classroom
    assert "Work Average" in classroom
    assert "Work Completion" in classroom
    assert "OJT Hour Progress" in classroom
    assert "Evidence Inventory" in classroom
    assert "Back to Classrooms" not in classroom


def test_admin_program_filter_is_driven_by_actual_student_rows():
    students = _text("resources/views/admin/students.html")
    admin_consistency = _text("resources/views/components/admin_consistency.html")

    # Legacy template values remain harmless because the shared Admin layer
    # rebuilds both controls from the actual rendered student rows at runtime.
    assert 'data-program="{{ (student.major_program|lower)' in students
    assert "document.querySelectorAll('#studentsTable tbody tr[data-program]')" in admin_consistency
    assert "filter.innerHTML = ''" in admin_consistency
    assert "programs.forEach" in admin_consistency
    assert "customInput.placeholder = 'Enter program or abbreviation (example: BSIT)'" in admin_consistency


def test_admin_classroom_and_document_folder_render_with_existing_profile_data():
    suffix = uuid.uuid4().hex[:8]
    conn = get_db_connection()
    supervisor_id = _create_user(conn, f"adminpass_sup_{suffix}", "supervisor")
    student_id = _create_user(conn, f"adminpass_stu_{suffix}", "student")

    classroom_id = conn.execute(
        """
        INSERT INTO classrooms
            (name,section,description,supervisor_id,code,classroom_type,archived)
        VALUES (?,?,?,?,?,?,?) RETURNING id
        """,
        (
            "Admin Consistency Intern",
            "BSIT-4A",
            "Read-only Admin classroom regression fixture.",
            supervisor_id,
            f"NXR-A{suffix.upper()}",
            "internship",
            0,
        ),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO student_profiles
            (user_id,first_name,last_name,age,student_id,phone_number,home_address,
             grade_year,major_program,emergency_name,emergency_relationship,
             emergency_phone,emergency_email,profile_completed)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            student_id,
            "Admin",
            "Fixture",
            21,
            f"26-{suffix[:4]}",
            "09171234567",
            "Taguig City",
            "4th Year",
            "Bachelor of Science in Information Technology",
            "Emergency Person",
            "Parent",
            "09179876543",
            "emergency@example.com",
            1,
        ),
    )
    conn.execute(
        "INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)",
        (classroom_id, student_id),
    )
    conn.execute(
        """
        INSERT INTO classroom_internship_details
            (classroom_id,internship_title,company_name,industry,work_arrangement,
             schedule_type,hours_mode,compensation,location,required_hours,
             company_description,internship_description)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
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
            486,
            "Software company",
            "Build internship projects",
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
    _login_as_admin(client)
    fake_report = {
        "overall_percentage": 82.5,
        "completion_rate": 75.0,
        "performance_label": "Satisfactory",
    }

    try:
        with patch(
            "app.Http.Controllers.admin_classrooms.build_class_reports",
            return_value=[fake_report],
        ):
            classroom_response = client.get(f"/admin/classrooms/{classroom_id}")
        assert classroom_response.status_code == 200
        classroom_body = classroom_response.get_data(as_text=True)
        assert "Software Engineering Intern" in classroom_body
        assert "Nexora Labs" in classroom_body
        assert "Overall Insights" in classroom_body
        assert "82.5%" in classroom_body
        assert "75.0%" in classroom_body

        folder_response = client.get(f"/admin/student-documents/{student_id}")
        assert folder_response.status_code == 200
        folder_body = folder_response.get_data(as_text=True)
        assert "Complete Student Information" in folder_body
        assert "09171234567" in folder_body
        assert "Emergency Person" in folder_body
        assert "Bachelor of Science in Information Technology" in folder_body
    finally:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM classroom_internship_responsibilities WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classroom_internship_qualifications WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classroom_internship_details WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM classroom_students WHERE classroom_id = ?", (classroom_id,))
            conn.execute("DELETE FROM student_profiles WHERE user_id = ?", (student_id,))
            conn.execute("DELETE FROM classrooms WHERE id = ?", (classroom_id,))
            conn.execute("DELETE FROM users WHERE id IN (?, ?)", (student_id, supervisor_id))
            conn.commit()
        finally:
            conn.close()
