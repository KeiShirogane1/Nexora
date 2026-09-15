from datetime import datetime
from unittest.mock import MagicMock, patch

from app.Services import internship_schedule_service as schedule_service
from app.Services import logbook_review_service, logbook_service


def _cursor(*, one=None, many=None):
    cursor = MagicMock()
    cursor.fetchone.return_value = one
    cursor.fetchall.return_value = many or []
    return cursor


def test_student_day_numbers_collapse_duplicate_calendar_dates():
    conn = MagicMock()
    conn.execute.return_value = _cursor(
        many=[
            {"id": 11, "clock_in": "2026-09-15T08:00:00"},
            {"id": 12, "clock_in": "2026-09-15T13:00:00"},
            {"id": 13, "clock_in": "2026-09-16T08:00:00"},
        ]
    )

    day_map = logbook_service._attendance_day_map(conn, 7, 3)

    assert day_map == {11: 1, 12: 1, 13: 2}


def test_supervisor_day_numbers_are_distinct_per_student_and_date():
    conn = MagicMock()
    conn.execute.return_value = _cursor(
        many=[
            {"id": 21, "student_id": 7, "clock_in": "2026-09-15T08:00:00"},
            {"id": 22, "student_id": 7, "clock_in": "2026-09-15T13:00:00"},
            {"id": 23, "student_id": 7, "clock_in": "2026-09-16T08:00:00"},
            {"id": 31, "student_id": 8, "clock_in": "2026-09-15T09:00:00"},
        ]
    )

    day_map = logbook_review_service._day_map(conn, 3)

    assert day_map == {21: 1, 22: 1, 23: 2, 31: 1}


def test_schedule_state_blocks_second_clock_in_after_completed_day():
    conn = MagicMock()

    def execute(sql, params=None):
        normalized = " ".join(sql.split())
        if "FROM classroom_students cs" in normalized and "c.id = ?" in normalized:
            return _cursor(one={"id": 3})
        if "FROM classroom_internship_details" in normalized:
            return _cursor(
                one={
                    "schedule_type": "weekly",
                    "hours_per_day": 8,
                    "required_days": 10,
                    "required_hours": 80,
                    "attendance_days": "mon,tue,wed,thu,fri",
                    "shift_start_time": "09:00",
                    "shift_end_time": "17:00",
                }
            )
        if "SELECT clock_in, COALESCE(hours_rendered, 0) AS hours_rendered" in normalized:
            return _cursor(
                many=[
                    {"clock_in": "2026-09-16T09:00:00", "hours_rendered": 1.0},
                ]
            )
        if "SELECT id, clock_in, status" in normalized:
            return _cursor(
                many=[
                    {"id": 41, "clock_in": "2026-09-16T09:00:00", "status": "Completed"},
                ]
            )
        if "status = 'Open'" in normalized:
            return _cursor(one=None)
        raise AssertionError(f"Unexpected SQL: {normalized}")

    conn.execute.side_effect = execute

    with patch.object(schedule_service, "ensure_internship_schedule_schema", return_value=None), patch.object(
        schedule_service,
        "get_db_connection",
        return_value=conn,
    ):
        state = schedule_service.get_student_schedule_state(
            7,
            3,
            now=datetime(2026, 9, 16, 10, 0, 0),
        )

    assert state["completed_today"] is True
    assert state["has_attendance_today"] is True
    assert state["can_clock_in"] is False
    assert "next OJT day" in state["clock_in_block_reason"]


def test_schedule_state_blocks_non_scheduled_weekday():
    conn = MagicMock()

    def execute(sql, params=None):
        normalized = " ".join(sql.split())
        if "FROM classroom_students cs" in normalized and "c.id = ?" in normalized:
            return _cursor(one={"id": 3})
        if "FROM classroom_internship_details" in normalized:
            return _cursor(
                one={
                    "schedule_type": "weekly",
                    "hours_per_day": 8,
                    "required_days": 10,
                    "required_hours": 80,
                    "attendance_days": "mon,tue,wed,thu,fri",
                    "shift_start_time": "09:00",
                    "shift_end_time": "17:00",
                }
            )
        if "SELECT clock_in, COALESCE(hours_rendered, 0) AS hours_rendered" in normalized:
            return _cursor(many=[])
        if "SELECT id, clock_in, status" in normalized:
            return _cursor(many=[])
        if "status = 'Open'" in normalized:
            return _cursor(one=None)
        raise AssertionError(f"Unexpected SQL: {normalized}")

    conn.execute.side_effect = execute

    with patch.object(schedule_service, "ensure_internship_schedule_schema", return_value=None), patch.object(
        schedule_service,
        "get_db_connection",
        return_value=conn,
    ):
        state = schedule_service.get_student_schedule_state(
            7,
            3,
            now=datetime(2026, 9, 20, 10, 0, 0),  # Sunday
        )

    assert state["is_scheduled_day"] is False
    assert state["can_clock_in"] is False
    assert "not a scheduled" in state["clock_in_block_reason"]


def test_clock_in_request_guard_blocks_completed_day(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 99071
        sess["role"] = "student"

    blocked_state = {
        "classroom_id": 3,
        "can_clock_in": False,
        "clock_in_block_reason": "Today's OJT attendance is already completed. Clock In will be available on your next OJT day.",
    }
    with patch(
        "app.Http.Controllers.daily_logbook.get_student_schedule_state",
        return_value=blocked_state,
    ):
        response = client.post("/student/clock-in", follow_redirects=False)

    assert response.status_code in (302, 303)
    assert "/student/logbook?classroom_id=3" in response.headers.get("Location", "")


def test_student_topbar_exposes_clock_in_block_and_day_number_sync():
    source = open("resources/views/components/student_topbar.html", encoding="utf-8").read()
    assert "clock_in_block_reason" in source
    assert "attendance_day_numbers" in source
    assert "student-logbook-history-day" in source
