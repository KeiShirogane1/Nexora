import ast
from pathlib import Path

from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_modified_python_and_templates_parse():
    ast.parse(_source("app/Http/Controllers/logbook_review.py"))
    env = Environment()
    for relative_path in (
        "resources/views/components/supervisor_topbar.html",
        "resources/views/components/admin_topbar.html",
        "resources/views/admin/student_logbooks.html",
        "resources/views/student/logbook_review.html",
    ):
        env.parse(_source(relative_path))


def test_approve_flow_saves_daily_performance_and_requires_rating():
    controller = _source("app/Http/Controllers/logbook_review.py")
    supervisor_topbar = _source("resources/views/components/supervisor_topbar.html")

    assert 'status == "approved" and not star_rating and not existing_rating' in controller
    assert "save_daily_performance_rating(" in controller
    assert 'request.form.get("star_rating")' in controller
    assert "Approve & Save Rating" in supervisor_topbar
    assert "copyRatingIntoReview" in supervisor_topbar
    assert 'name="star_rating"' in supervisor_topbar


def test_additional_daily_rating_criteria_use_existing_storage_without_hidden_weighting():
    controller = _source("app/Http/Controllers/logbook_review.py")
    rating_service = _source("app/Services/performance_rating_service.py")
    supervisor_topbar = _source("resources/views/components/supervisor_topbar.html")
    student_review = _source("resources/views/student/logbook_review.html")

    assert "daily_performance_rating_items" in rating_service
    assert "daily_performance_rating_items" in controller
    assert 'name="criterion_name"' in supervisor_topbar
    assert 'name="criterion_rating"' in supervisor_topbar
    assert "Additional Rating Criteria" in supervisor_topbar
    assert "do not silently change the Overall Daily Rating" in supervisor_topbar
    assert "daily_rating.criteria" in student_review
    assert "do not replace or automatically re-weight the Overall Daily Rating" in student_review
    assert "ML Insights and Reports" in student_review


def test_supervisor_and_admin_can_remove_daily_logbook_but_attendance_is_preserved():
    controller = _source("app/Http/Controllers/logbook_review.py")
    supervisor_topbar = _source("resources/views/components/supervisor_topbar.html")
    admin_topbar = _source("resources/views/components/admin_topbar.html")
    admin_page = _source("resources/views/admin/student_logbooks.html")

    assert '/supervisor/classes/<int:class_id>/logbook/<int:log_id>/delete' in controller
    assert '/admin/student/<int:student_id>/logbook/<int:log_id>/delete' in controller
    assert '@role_required("supervisor")' in controller
    assert '@role_required("admin")' in controller
    assert 'c.supervisor_id' in controller
    assert 'DELETE FROM logs WHERE id = ? AND entry_type = \'daily\'' in controller
    assert "DELETE FROM logbook_reviews" in controller
    assert "DELETE FROM daily_log_work_links" in controller
    assert "DELETE FROM logbook_photos" in controller
    assert "DELETE FROM daily_performance_ratings" in controller
    assert "remove_attendance=False" in controller
    assert "if remove_attendance:" in controller
    assert "DELETE FROM attendance WHERE id = ? AND student_id = ? AND classroom_id = ?" in controller
    assert "attendance Time In/Out and rendered hours" in controller
    assert "Remove Logbook" in supervisor_topbar
    assert "Manage OJT Logbook" in admin_topbar
    assert "Remove Logbook" in admin_page


def test_removed_logbook_notification_identifies_ojt_day_and_date():
    controller = _source("app/Http/Controllers/logbook_review.py")

    assert "_attendance_day_details" in controller
    assert "attendance_local_datetime" in controller
    assert "Daily OJT Logbook Removed" in controller
    assert "day_number" in controller
    assert "date_label" in controller
    assert "attendance Time In/Out and rendered hours were not deleted" in controller


def test_logbook_removal_resyncs_affected_work_scores_from_remaining_rated_days():
    controller = _source("app/Http/Controllers/logbook_review.py")

    assert "_resync_work_score_after_log_removal" in controller
    assert "AVG(r.percentage)" in controller
    assert "JOIN daily_performance_ratings" in controller
    assert "daily_log_work_links" in controller
    assert "related_assignment_id" in controller
    assert "DELETE FROM classwork_scores" in controller
    assert "'daily_performance'" in controller


def test_supervisor_and_admin_shared_desktop_gutters_remove_nested_width_caps():
    shell_css = _source("resources/assets/css/sidebars.css")

    assert "--nx-supervisor-page-gutter: 30px" in shell_css
    assert ".nexora-class-page" in shell_css
    assert "padding-left: 0 !important" in shell_css
    assert "--nx-admin-page-gutter: 30px" in shell_css
    assert ".admin-main > :first-child" in shell_css
    assert ".admin-polish-page" in shell_css
