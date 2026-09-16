def test_student_logbook_badge_hides_when_attention_is_inactive():
    source = open("resources/views/components/student_topbar.html", encoding="utf-8").read()

    assert ".nx-role-student .nx-role-badge[hidden]" in source
    assert "display: none !important" in source
    assert "hasOpenAttendance" in source
    assert "completedToday" in source
    assert "logbookBadge.hidden = true" in source


def test_supervisor_review_warns_when_daily_performance_is_not_rated():
    source = open("app/Http/Controllers/logbook_review.py", encoding="utf-8").read()

    assert "get_daily_performance_rating_for_supervisor" in source
    assert "this Daily OJT entry is not graded yet" in source
    assert "Choose Daily Performance and click Save Rating" in source


def test_daily_performance_success_reports_linked_work_sync():
    controller_source = open(
        "app/Http/Controllers/logbook_review.py", encoding="utf-8"
    ).read()
    rating_source = open(
        "app/Services/performance_rating_service.py", encoding="utf-8"
    ).read()

    assert "linked_assignment_ids" in controller_source
    assert "Applied to" in controller_source
    assert "_sync_attendance_work_score" in rating_source
    assert "daily_log_work_links" in rating_source
