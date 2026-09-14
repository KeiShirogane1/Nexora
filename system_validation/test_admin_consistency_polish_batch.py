from pathlib import Path

from app.Services.profile_service import normalize_program_name


ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_program_aliases_normalize_and_custom_program_is_preserved():
    assert normalize_program_name("BSIT") == "Bachelor of Science in Information Technology"
    assert normalize_program_name("BSCS") == "Bachelor of Science in Computer Science"
    assert normalize_program_name("BSIS") == "Bachelor of Science in Information Systems"
    assert normalize_program_name("BSCPE") == "Bachelor of Science in Computer Engineering"
    assert normalize_program_name("Bachelor of Science in Data Science") == "Bachelor of Science in Data Science"


def test_admin_student_program_choices_are_database_driven_and_saved_canonical():
    source = _read("app/Http/Controllers/admin.py")
    assert "normalize_program_name" in source
    assert 'programs_raw + ["BSIT", "BS Information Technology", "BSCS"]' not in source
    assert "program = normalize_program_name(" in source
    assert "SELECT DISTINCT major_program FROM student_profiles" in source

    template = _read("resources/views/admin/students.html")
    assert 'id="programFilter"' in template
    assert 'data-nx-program-database="true"' in template
    assert "{% for program in programs %}" in template
    assert '<option value="bsit">BSIT</option>' not in template
    assert '<option value="bscs">BSCS</option>' not in template
    assert '<option value="other">Other</option>' not in template
    assert 'program === "other"' not in template
    assert "program_abbreviations" in template
    assert "'bachelor of science in information technology': 'BSIT'" in template
    assert "'bachelor of science in computer science': 'BSCS'" in template
    assert "'bachelor of science in information systems': 'BSIS'" in template
    assert "'bachelor of science in computer engineering': 'BSCPE'" in template
    assert 'data-full-program="{{ student.major_program or \'\' }}"' in template
    assert 'class="table-meta text-nowrap"' in template
    assert 'title="{{ student.major_program }}"' in template
    assert "program_label[:25] ~ '…'" in template
    assert 'cells[5].getAttribute("data-full-program")' in template

    shell = _read("resources/views/components/admin_sidebar.html")
    assert "nxProgramDatabase" in shell
    assert "programFilter" in shell
    assert "All Programs" in shell

    shared = _read("resources/views/components/nexora_people_actions.html")
    assert "select.dataset.nxProgramDatabase==='true'" in shared


def test_admin_student_documents_landing_has_no_obsolete_classroom_type_filter():
    template = _read("resources/views/admin/student_documents.html")
    assert 'name="type"' not in template
    assert "All Classroom Types" not in template
    assert "Classroom Type" not in template
    assert 'name="documents"' in template
    assert 'name="search"' in template


def test_admin_classroom_landing_removes_type_filter_but_keeps_type_display():
    template = _read("resources/views/admin/classrooms.html")
    assert 'id="classroomType"' not in template
    assert 'name="type"' not in template
    assert ">All Types<" not in template
    assert '<th>Type</th>' in template
    assert "Intern Classroom" in template
    assert 'name="search"' in template
    assert 'name="status"' in template
    assert ">Reset<" in template
    assert ">Apply<" in template


def test_admin_shared_shell_matches_dashboard_heading_and_gutters():
    css = _read("resources/assets/css/admin.css")
    shared = _read("resources/views/components/admin_topbar.html")
    assert "ADMIN SHARED DASHBOARD-ALIGNED PAGE SHELL" in css
    assert "--nx-admin-ui-shell-max: 1480px" in css
    assert "--nx-admin-ui-gutter: 28px" in css
    assert "font-size: clamp(2rem, 3vw, 2.7rem)" in css
    assert "letter-spacing: -0.045em" in css
    assert 'content: "ADMIN PORTAL"' in css
    assert "font-size: 0.93rem" in css
    assert ":not(.admin-dashboard-page) .admin-main" in css
    assert "grid-template-columns: minmax(260px, 1fr) 190px auto" in css
    assert 'id="nx-admin-dashboard-aligned-ui"' not in shared
    assert 'id="nx-admin-compact-topbar-reserve-fix"' in shared
    assert "padding-top: 68px !important" in shared
    assert "padding-top: 64px !important" in shared
    assert ":not(.admin-dashboard-page) .admin-main > :first-child" in shared
    assert "margin-top: 24px !important" in shared
    assert "margin-top: 20px !important" in shared


def test_admin_document_route_remains_protected_and_txt_can_download():
    source = _read("app/Http/Controllers/admin_classrooms.py")
    assert '@role_required("admin")' in source
    assert "WHERE id = ? AND student_id = ?" in source
    assert "_is_safe_upload_path(filepath)" in source
    assert 'request.args.get("download") == "1"' in source
    assert "as_attachment=download_requested" in source


def test_admin_document_folder_has_explicit_image_pdf_txt_action_matrix():
    template = _read("resources/views/admin/student_document_folder.html")
    assert "js-admin-image-preview" in template
    assert "window.NexoraDocumentViewer.open" in template
    assert "Open PDF" in template
    assert 'target="_blank"' in template
    assert "?download=1" in template
    assert ">Download<" in template
    assert "School Email" in template
    assert "Emergency Contact" in template
    assert "Profile Completed" in template
    assert "Profile Created" in template
    assert "profile_picture }}" not in template


def test_admin_classroom_detail_keeps_work_and_official_evaluation_separate():
    source = _read("app/Http/Controllers/admin_classrooms.py")
    template = _read("resources/views/admin/classroom_detail.html")
    css = _read("resources/assets/css/admin.css")
    assert "build_class_reports(classroom_id)" in source
    assert "ojt_evaluations" in source
    assert "<progress" in template
    assert "No combined score" in template
    assert "CLASSROOM-SCOPED WORK EVIDENCE" in template
    assert "Official OJT Evaluation" in template
    assert "separate manual supervisor-entered record" in template
    assert "not included in Work, ML, attendance, or logbook metrics" in template
    assert "admin-evaluation-note" in template
    assert ".admin-evaluation-note" in css
    assert "padding: 0 16px 18px" in css
    assert "required_hours" in template


def test_admin_insights_keeps_evidence_dimensions_read_only_and_separate():
    template = _read("resources/views/admin/student_insights.html")
    assert "READ-ONLY ADMINISTRATION" in template
    assert "Work Performance" in template
    assert "Attendance &amp; Logbook" in template
    assert "Daily Performance" in template
    assert "ML Signals" in template
    assert "Official OJT Evaluation" in template
    assert "separate evidence dimensions" in template
    assert "not merged with ML, Work, attendance, Daily Performance, or Logbook" in template


def test_student_class_menu_removes_duplicate_information_action_only():
    template = _read("resources/views/components/student_class_shell.html")
    assert ">Classroom Information<" not in template
    assert ">Classroom Info<" in template
    assert "Intern Classroom Information" in template
    assert "Copy Classroom Code" in template
    assert "Leave Intern Classroom" in template
    assert "studentClassInfoUrl" in template


def test_username_copy_control_is_subtle_and_accessible():
    shared = _read("resources/views/components/nexora_people_actions.html")
    assert ".nx-copy-username{width:1.05em" in shared
    assert "border:0!important" in shared
    assert "background:transparent!important" in shared
    assert "copy.title='Copy username'" in shared
    assert "copy.setAttribute('aria-label','Copy @'+username)" in shared
    assert "Username copied." in shared


def test_modal_close_buttons_are_transparent_with_red_interaction_states():
    css = _read("resources/assets/css/modals.css")
    assert "SHARED CLOSE CONTROLS" in css
    assert ".nexora-modal-close.nexora-modal-close" in css
    assert ".nexora-logout-close.nexora-logout-close" in css
    assert ".crop-close.crop-close" in css
    assert ".modal-close.modal-close" in css
    assert ".admin-notification-close.admin-notification-close" in css
    assert "#nxDocumentViewerClose#nxDocumentViewerClose" in css
    assert "background: transparent !important" in css
    assert "border: 0 !important" in css
    assert "color: #dc2626 !important" in css
    assert "color: #991b1b !important" in css
    assert ":focus-visible" in css


def test_admin_shell_removes_only_literal_legacy_back_to_controls():
    shell = _read("resources/views/components/admin_sidebar.html")
    assert "removeLegacyBackControls" in shell
    assert "main a, main button" in shell
    assert "Back\\s+to" in shell
    assert "element.remove()" in shell
    assert "Reset" not in shell
    assert "Cancel" not in shell
