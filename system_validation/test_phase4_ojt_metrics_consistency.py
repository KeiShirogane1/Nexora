from unittest.mock import MagicMock, patch

from app.Services import classwork_ml_service, performance_report_service


def _cursor(*, one=None, many=None):
    cursor = MagicMock()
    cursor.fetchone.return_value = one
    cursor.fetchall.return_value = many or []
    return cursor


def test_ml_metrics_use_assigned_work_and_phase2_links():
    conn = MagicMock()
    captured = {}
    rows = [
        {
            "id": 11,
            "assignment_points": 0,
            "score": 90,
            "max_score": 100,
            "percentage": 90,
            "grading_method": "manual",
            "submission_grade": None,
            "is_recorded": 1,
            "is_reviewed": 1,
        },
        {
            "id": 14,
            "assignment_points": 0,
            "score": 80,
            "max_score": 100,
            "percentage": 80,
            "grading_method": "manual",
            "submission_grade": None,
            "is_recorded": 1,
            "is_reviewed": 0,
        },
    ]

    def execute(sql, params=None):
        captured["sql"] = " ".join(sql.split())
        captured["params"] = params
        return _cursor(many=rows)

    conn.execute.side_effect = execute

    with patch.object(classwork_ml_service, "get_db_connection", return_value=conn):
        features = classwork_ml_service.build_student_performance_features(7, 3)

    assert features["total_count"] == 2
    assert features["recorded_count"] == 2
    assert features["reviewed_count"] == 1
    assert features["graded_count"] == 2
    assert features["average_percentage"] == 85
    assert "classroom_assignment_recipients" in captured["sql"]
    assert "daily_log_work_links" in captured["sql"]
    assert "link.assignment_id = a.id" in captured["sql"]
    assert captured["params"][-2:] == (3, 7)


def test_report_feedback_prefers_daily_logbook_review():
    conn = MagicMock()
    calls = []

    def execute(sql, params=None):
        normalized = " ".join(sql.split())
        calls.append(normalized)
        if "FROM logbook_reviews r" in normalized:
            return _cursor(one={"comments": "Strong progress on today's assigned Work."})
        raise AssertionError(f"Unexpected fallback query: {normalized}")

    conn.execute.side_effect = execute

    with patch.object(performance_report_service, "get_db_connection", return_value=conn):
        feedback = performance_report_service._get_latest_feedback_text(7, 3)

    assert feedback == "Strong progress on today's assigned Work."
    assert len(calls) == 1


def test_report_work_list_uses_student_recipient_scope():
    source = open("app/Services/performance_report_service.py", encoding="utf-8").read()

    assert "classroom_assignment_recipients all_recipients" in source
    assert "classroom_assignment_recipients my_recipient" in source
    assert "my_recipient.student_id=?" in source
    assert '"recorded_count":features.get("recorded_count",0)' in source
    assert '"reviewed_count":features.get("reviewed_count",0)' in source
