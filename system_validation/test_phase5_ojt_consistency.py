from datetime import datetime
from unittest.mock import MagicMock, patch

from app.Http.Controllers import ojt_evaluation


def _cursor(*, one=None, many=None):
    cursor = MagicMock()
    cursor.fetchone.return_value = one
    cursor.fetchall.return_value = many or []
    return cursor


def test_dashboard_and_work_detail_recognize_secondary_logbook_work():
    dashboard_source = open(
        "app/Services/student_dashboard_service.py", encoding="utf-8"
    ).read()
    work_source = open(
        "app/Http/Controllers/student_classwork.py", encoding="utf-8"
    ).read()

    assert dashboard_source.count("FROM daily_log_work_links link") >= 2
    assert "link.assignment_id = a.id" in dashboard_source
    assert "FROM daily_log_work_links link" in work_source
    assert "link.assignment_id = ?" in work_source


def test_student_gradebook_uses_assignment_recipient_scope():
    source = open(
        "app/Http/Controllers/student_gradebook.py", encoding="utf-8"
    ).read()

    assert "classroom_assignment_recipients all_recipients" in source
    assert "classroom_assignment_recipients my_recipient" in source
    assert "my_recipient.student_id = ?" in source


def test_final_evaluation_readiness_counts_distinct_local_ojt_dates():
    conn = MagicMock()

    def execute(sql, params=None):
        normalized = " ".join(sql.split())
        if "FROM classrooms c" in normalized:
            return _cursor(
                one={
                    "id": 3,
                    "schedule_type": "weekly",
                    "required_days": 2,
                }
            )
        if "FROM classroom_students cs LEFT JOIN attendance a" in normalized:
            return _cursor(
                many=[
                    {"student_id": 7, "clock_in": "first", "status": "Completed"},
                    {"student_id": 7, "clock_in": "duplicate", "status": "Completed"},
                    {"student_id": 7, "clock_in": "second", "status": "Completed"},
                ]
            )
        raise AssertionError(f"Unexpected SQL: {normalized}")

    conn.execute.side_effect = execute

    with patch.object(ojt_evaluation, "get_db_connection", return_value=conn), patch.object(
        ojt_evaluation,
        "attendance_local_datetime",
        side_effect=[
            datetime(2026, 9, 15, 8, 0),
            datetime(2026, 9, 15, 13, 0),
            datetime(2026, 9, 16, 8, 0),
        ],
    ):
        readiness = ojt_evaluation._classroom_evaluation_readiness(2, 3)

    assert readiness["configured"] is True
    assert readiness["minimum_completed_days"] == 2
    assert readiness["days_left"] == 0
    assert readiness["available"] is True


def test_daily_rating_and_official_evaluation_remain_separate():
    daily_rating_source = open(
        "app/Services/performance_rating_service.py", encoding="utf-8"
    ).read()
    official_evaluation_source = open(
        "app/Services/ojt_evaluation_service.py", encoding="utf-8"
    ).read()

    assert "ojt_evaluations" not in daily_rating_source
    assert "ojt_evaluation_items" not in daily_rating_source
    assert "daily_performance_ratings" not in official_evaluation_source
    assert "classwork_scores" not in official_evaluation_source
