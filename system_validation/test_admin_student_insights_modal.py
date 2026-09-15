from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_insights_route_degrades_optional_evidence_instead_of_500():
    source = _read("app/Http/Controllers/admin_reports_overview.py")

    assert "current_app.logger.exception" in source
    assert "_empty_student_report" in source
    assert "Work and ML evidence is temporarily unavailable." in source
    assert "Attendance, Daily Performance, and Logbook evidence is temporarily unavailable." in source
    assert "Official OJT Evaluation is temporarily unavailable." in source


def test_admin_insights_links_open_in_shared_modal():
    source = _read("resources/views/components/admin_topbar.html")

    assert "nxAdminStudentInsightsModal" in source
    assert "main a[href*=\"/admin/insights\"]" in source
    assert "new DOMParser().parseFromString" in source
    assert "content.querySelector('.admin-polish-header')" in source
    assert "content.querySelector('.admin-insights-selector')" in source


def test_assigned_interns_replaces_documents_action_with_insights():
    source = _read("resources/views/admin/assigned_interns.html")

    assert "admin_reports_overview.student_insights" in source
    assert ">Insights</a>" in source
    assert "admin_classrooms.student_document_folder" not in source


def test_admin_student_program_label_is_compact_and_filter_value_stays_full():
    source = _read("resources/views/components/admin_topbar.html")

    assert "restoreCompactAdminPrograms" in source
    assert "'bachelor of science in information technology': 'BSIT'" in source
    assert "row.dataset.program = full.toLowerCase()" in source
    assert "#studentsTable td[data-full-program] .table-meta" in source


def test_admin_classroom_roster_keeps_existing_insights_destination():
    source = _read("resources/views/admin/classroom_detail.html")

    assert "admin_reports_overview.student_insights" in source
    assert ">Insights</a>" in source
