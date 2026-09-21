from unittest.mock import MagicMock, patch

from app.Services import classwork_ml_service
from app.Services import performance_report_service


def _cursor(*, one=None, many=None):
    cursor = MagicMock()
    cursor.fetchone.return_value = one
    cursor.fetchall.return_value = many or []
    return cursor


def test_ml_prefers_daily_performance_over_stale_classwork_score():
    conn = MagicMock()
    conn.execute.return_value = _cursor(
        many=[
            {
                "id": 11,
                "assignment_points": 100,
                "score": 20,
                "max_score": 100,
                "percentage": 20,
                "grading_method": "manual",
                "daily_rating_percentage": 92,
                "submission_grade": None,
                "is_recorded": 1,
                "is_reviewed": 1,
            }
        ]
    )

    with patch.object(classwork_ml_service, "get_db_connection", return_value=conn):
        features = classwork_ml_service.build_student_performance_features(3, 7)

    assert features["average_percentage"] == 92
    assert features["graded_count"] == 1
    assert features["daily_performance_count"] == 1
    assert features["manual_count"] == 0
    assert features["completion_rate"] == 100

    sql = " ".join(conn.execute.call_args.args[0].split())
    assert "JOIN daily_performance_ratings dpr" in sql
    assert "LEFT JOIN daily_log_work_links rated_link" in sql
    assert "rated_attendance.id = rated_log.attendance_id" in sql


def test_report_work_item_uses_daily_performance_rating_directly():
    conn = MagicMock()

    def execute(sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT u.id,u.username"):
            return _cursor(
                one={
                    "id": 3,
                    "username": "student",
                    "email": "student@example.test",
                    "student_number": "S-3",
                }
            )
        if normalized.startswith("SELECT c.id,c.name"):
            return _cursor(
                one={
                    "id": 7,
                    "name": "Intern Classroom",
                    "section": "A",
                    "code": "ABC123",
                    "supervisor_id": 2,
                    "sup_name": "teacher",
                    "sup_email": "teacher@example.test",
                }
            )
        if "FROM classroom_assignments a LEFT JOIN classwork_scores" in normalized:
            return _cursor(
                many=[
                    {
                        "id": 11,
                        "title": "Group Work",
                        "points": 100,
                        "score": 10,
                        "max_score": 100,
                        "percentage": 10,
                        "grading_method": "manual",
                        "daily_rating_percentage": 94,
                        "submission_grade": None,
                    }
                ]
            )
        raise AssertionError(f"Unexpected SQL: {normalized}")

    conn.execute.side_effect = execute
    analysis = {
        "features": {
            "average_percentage": 94,
            "min_percentage": 94,
            "max_percentage": 94,
            "graded_count": 1,
            "total_count": 1,
            "recorded_count": 1,
            "reviewed_count": 1,
            "recorded_completion_rate": 100,
            "review_rate": 100,
            "completion_rate": 100,
            "daily_performance_count": 1,
            "manual_count": 0,
            "imported_count": 0,
        },
        "numeric_performance_label": "Excellent",
        "performance_label": "Excellent",
        "feedback_analysis": {"is_empty": True},
    }

    with patch.object(performance_report_service, "build_student_ml_analysis", return_value=analysis), patch.object(
        performance_report_service, "build_recommendation_from_features", return_value={
            "recommendation": "",
            "priority": "none",
            "basis": [],
        }, create=True
    ), patch.object(performance_report_service, "get_db_connection", return_value=conn):
        report = performance_report_service.build_student_report(3, 7, feedback_text="")

    assert report["overall_percentage"] == 94
    assert report["graded_count"] == 1
    assert report["assignments"][0]["percentage"] == 94
    assert report["assignments"][0]["score"] == 94
    assert report["assignments"][0]["max_score"] == 100
    assert report["assignments"][0]["grading_method"] == "Daily Performance"


def test_role_portals_share_documents_sized_desktop_gutter():
    shell_css = open("resources/assets/css/sidebars.css", encoding="utf-8").read()

    assert "--nx-supervisor-page-gutter: 30px" in shell_css
    assert "--nx-admin-page-gutter: 30px" in shell_css
    assert ".supervisor-classwork-shell" in shell_css
    assert ".admin-command-center" in shell_css
