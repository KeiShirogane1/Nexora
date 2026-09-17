from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_management_directory_endpoints_remain_admin_only():
    controller = _source("app/Http/Controllers/admin_assigned_interns.py")

    assert (
        '@admin_assigned_interns.route("/admin/management-directory/students")\n'
        '@role_required("admin")\n'
        'def student_management_context():'
    ) in controller
    assert (
        '@admin_assigned_interns.route("/admin/management-directory/supervisors")\n'
        '@role_required("admin")\n'
        'def supervisor_management_context():'
    ) in controller
    assert "return jsonify(get_admin_student_management_context())" in controller
    assert "return jsonify(get_admin_supervisor_management_context())" in controller


def test_management_directory_read_models_reuse_existing_data_without_writes():
    source = _source("app/Services/admin_assigned_interns_service.py")
    directory_source = source.split("def get_admin_student_management_context", 1)[1]

    assert "LEFT JOIN student_profiles" in directory_source
    assert "JOIN classroom_students" in directory_source
    assert "FROM student_assignments" in directory_source
    assert "LEFT JOIN supervisor_profiles" in directory_source
    assert "LEFT JOIN classroom_internship_details" in directory_source
    assert "UNION" in directory_source
    assert '"profile_picture_url"' in directory_source
    assert '"student_number"' in directory_source
    assert '"grade_year"' in directory_source
    assert '"assigned_students"' in directory_source

    for write_statement in (
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "ALTER TABLE",
        "CREATE TABLE",
        "DROP TABLE",
    ):
        assert write_statement not in directory_source


def test_student_management_keeps_actions_and_adds_richer_responsive_directory():
    template = _source("resources/views/admin/students.html")

    assert '<meta name="viewport" content="width=device-width, initial-scale=1.0">' in template
    assert template.count("{% include 'components/admin_sidebar.html' %}") == 1
    assert "Student ID" in template
    assert "Program / Section" in template
    assert "Class / Internship" in template
    assert "Program / Course" in template
    assert "studentSearch" in template
    assert "supervisorFilter" in template
    assert "programFilter" in template
    assert "classFilter" in template
    assert "yearFilter" in template
    assert 'data-group-mode="program"' in template
    assert 'data-group-mode="class"' in template
    assert "admin_assigned_interns.student_management_context" in template
    assert "url_for('user_profile_picture', user_id=student.id)" in template
    assert 'data-student-username' in template
    assert 'data-student-email' in template
    assert 'data-program-cell' in template
    assert 'data-year-section' in template
    assert 'student-class-badge' in template
    assert "cell.colSpan = 9;" in template
    assert 'row.querySelector("[data-program-cell]")' in template
    assert "csrf_token()" in template
    assert "admin.bulk_action" in template
    assert "admin.create_student" in template
    assert "col-12 col-sm-6 col-xl-3" in template

    for stylesheet in ("css/style.css", "css/admin.css", "css/modals.css"):
        assert stylesheet in template
    assert "management.css" not in template


def test_supervisor_management_adds_profile_workload_grouping_and_responsive_controls():
    template = _source("resources/views/admin/supervisors.html")

    assert '<meta name="viewport" content="width=device-width, initial-scale=1.0">' in template
    assert template.count("{% include 'components/admin_sidebar.html' %}") == 1
    assert "Employee ID" in template
    assert "Department" in template
    assert "Assigned Classes" in template
    assert "Program Focus" in template
    assert "Assigned Students" in template
    assert "supervisorSearch" in template
    assert "departmentFilter" in template
    assert "programFilter" in template
    assert "classFilter" in template
    assert 'data-group-mode="class"' in template
    assert 'data-group-mode="program"' in template
    assert 'data-group-mode="department"' in template
    assert "admin_assigned_interns.supervisor_management_context" in template
    assert "supervisor.profile_picture_url" in template
    assert "data-supervisor-avatar" in template
    assert "csrf_token()" in template
    assert "admin.bulk_action" in template
    assert "admin.create_supervisor" in template
    assert "col-12 col-sm-6 col-xl" in template

    for stylesheet in ("css/style.css", "css/admin.css", "css/modals.css"):
        assert stylesheet in template
    assert "management.css" not in template


def test_directory_grouping_is_client_side_and_preserves_existing_rows():
    students = _source("resources/views/admin/students.html")
    supervisors = _source("resources/views/admin/supervisors.html")

    assert 'let groupMode = "all";' in students
    assert "function renderGroups()" in students
    assert "data-original-index" in students
    assert "data-class-ids" in students
    assert "data-primary-class" in students

    assert 'let groupMode="all";' in supervisors
    assert "function renderGroups()" in supervisors
    assert "data-original-index" in supervisors
    assert "data-class-ids" in supervisors
    assert "data-primary-class" in supervisors
    assert "data-primary-program" in supervisors


def test_management_directories_have_mobile_card_responsive_guardrails():
    typography = _source("resources/views/components/global_typography.html")
    responsive = _source("resources/views/components/admin_management_responsive.html")

    assert "nx_topbar_role|default('') == 'admin'" in typography
    assert "components/admin_management_responsive.html" in typography
    assert '<style id="nx-admin-management-responsive">' in responsive
    assert "@media (min-width: 681px) and (max-width: 1279px)" in responsive
    assert "@media (max-width: 680px)" in responsive
    assert "body.admin-students-page #studentsTable thead" in responsive
    assert "body.admin-supervisors-page #supervisorsTable thead" in responsive
    assert 'content: "Student ID";' in responsive
    assert 'content: "Program / Section";' in responsive
    assert 'content: "Class / Internship";' in responsive
    assert 'content: "Employee ID";' in responsive
    assert 'content: "Assigned Classes";' in responsive
    assert ".bulk-actions" in responsive
    assert ".nexora-modal-footer" in responsive
    assert "overflow: visible !important;" in responsive
    assert "management.css" not in responsive


def test_student_directory_desktop_uses_nine_semantic_columns_without_forced_overflow():
    template = _source("resources/views/admin/students.html")
    responsive = _source("resources/views/components/admin_management_responsive.html")

    assert template.count("<th") >= 9
    assert 'class="student-col-identity"' in template
    assert 'class="student-col-program"' in template
    assert 'class="student-col-class"' in template
    assert 'class="student-col-actions"' in template
    assert 'colspan="9"' in template
    assert "@media (min-width: 1280px)" in responsive
    assert "table-layout: fixed" in responsive
    assert ".student-col-identity" in responsive
    assert ".student-col-actions" in responsive
    assert "overflow-x: visible !important;" not in responsive
