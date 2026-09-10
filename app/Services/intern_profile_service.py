"""Classroom-scoped supervisor view of one intern's OJT evidence.

This service intentionally keeps attendance, Daily Performance, Logbook, and
Work as separate dimensions. It does not calculate a combined grade.
"""
from datetime import datetime

from app.Models.db import get_db_connection
from app.Services.daily_performance_history_service import (
    get_supervisor_daily_performance_history,
)


def _value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except AttributeError:
        pass
    try:
        value = row[index]
        return default if value is None else value
    except (IndexError, KeyError, TypeError):
        return default


def _as_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _format_datetime(value):
    parsed = _as_datetime(value)
    return parsed.strftime("%b %d, %Y · %I:%M %p").replace(" 0", " ") if parsed else "—"


def _format_date(value):
    parsed = _as_datetime(value)
    return parsed.strftime("%b %d, %Y") if parsed else "—"


def _display_name(row):
    first_name = str(_value(row, "first_name", 3, "") or "").strip()
    middle_name = str(_value(row, "middle_name", 4, "") or "").strip()
    last_name = str(_value(row, "last_name", 5, "") or "").strip()
    username = str(_value(row, "username", 1, "") or "").strip()
    parts = [part for part in (first_name, middle_name, last_name) if part]
    return " ".join(parts) if parts else username or "Intern"


def _classroom_dict(row):
    return {
        "id": int(_value(row, "id", 0, 0)),
        "name": _value(row, "name", 1, "Intern Classroom"),
        "section": _value(row, "section", 2, "") or "",
        "description": _value(row, "description", 3, "") or "",
        "code": _value(row, "code", 4, "") or "",
        "archived": bool(_value(row, "archived", 5, 0)),
        "company_name": _value(row, "company_name", 6, "") or "",
        "internship_title": _value(row, "internship_title", 7, "") or "",
        "work_arrangement": _value(row, "work_arrangement", 8, "") or "",
        "location": _value(row, "location", 9, "") or "",
        "hours_mode": _value(row, "hours_mode", 10, "not_specified") or "not_specified",
        "required_hours": float(_value(row, "required_hours", 11, 0) or 0),
        "start_date": _value(row, "start_date", 12, None),
        "end_date": _value(row, "end_date", 13, None),
    }


def _student_dict(row):
    return {
        "id": int(_value(row, "id", 0, 0)),
        "username": _value(row, "username", 1, "") or "",
        "email": _value(row, "email", 2, "") or "",
        "display_name": _display_name(row),
        "first_name": _value(row, "first_name", 3, "") or "",
        "middle_name": _value(row, "middle_name", 4, "") or "",
        "last_name": _value(row, "last_name", 5, "") or "",
        "student_number": _value(row, "student_number", 6, "") or "",
        "school_email": _value(row, "school_email", 7, "") or "",
        "phone_number": _value(row, "phone_number", 8, "") or "",
        "grade_year": _value(row, "grade_year", 9, "") or "",
        "major_program": _value(row, "major_program", 10, "") or "",
        "profile_completed": bool(_value(row, "profile_completed", 11, 0)),
    }


def _review_label(status):
    return {
        "pending": "Pending Review",
        "reviewed": "Reviewed",
        "approved": "Approved",
        "revision_requested": "Revision Requested",
        "in_progress": "In Progress",
    }.get(status, "Pending Review")


def _safe_percentage(score, max_score, stored_percentage):
    try:
        if stored_percentage is not None:
            return float(stored_percentage)
        if score is None or max_score is None or float(max_score) <= 0:
            return None
        return float(score) / float(max_score) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def get_supervisor_intern_profile(supervisor_id, classroom_id, student_id):
    """Return one enrolled intern's classroom-scoped OJT profile."""
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
        student_id = int(student_id)
    except (TypeError, ValueError):
        return {"ok": False, "status_code": 404}

    conn = get_db_connection()
    try:
        classroom_row = conn.execute(
            """
            SELECT c.id, c.name, c.section, c.description, c.code, c.archived,
                   COALESCE(cid.company_name, '') AS company_name,
                   COALESCE(cid.internship_title, '') AS internship_title,
                   COALESCE(cid.work_arrangement, '') AS work_arrangement,
                   COALESCE(cid.location, '') AS location,
                   COALESCE(cid.hours_mode, 'not_specified') AS hours_mode,
                   COALESCE(cid.required_hours, 0) AS required_hours,
                   cid.start_date, cid.end_date
            FROM classrooms c
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.id = ? AND c.supervisor_id = ?
            LIMIT 1
            """,
            (classroom_id, supervisor_id),
        ).fetchone()
        if not classroom_row:
            exists = conn.execute("SELECT 1 FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
            return {"ok": False, "status_code": 403 if exists else 404}

        student_row = conn.execute(
            """
            SELECT u.id, u.username, u.email,
                   COALESCE(sp.first_name, '') AS first_name,
                   COALESCE(sp.middle_name, '') AS middle_name,
                   COALESCE(sp.last_name, '') AS last_name,
                   COALESCE(sp.student_id, '') AS student_number,
                   COALESCE(sp.school_email, '') AS school_email,
                   COALESCE(sp.phone_number, '') AS phone_number,
                   COALESCE(sp.grade_year, '') AS grade_year,
                   COALESCE(sp.major_program, '') AS major_program,
                   COALESCE(sp.profile_completed, 0) AS profile_completed
            FROM classroom_students cs
            JOIN users u ON u.id = cs.student_id
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE cs.classroom_id = ? AND cs.student_id = ?
            LIMIT 1
            """,
            (classroom_id, student_id),
        ).fetchone()
        if not student_row:
            return {"ok": False, "status_code": 404}

        attendance_rows = conn.execute(
            """
            SELECT id, clock_in, clock_out, hours_rendered, status
            FROM attendance
            WHERE classroom_id = ? AND student_id = ?
            ORDER BY clock_in DESC, id DESC
            """,
            (classroom_id, student_id),
        ).fetchall()
        attendance_day_number_by_id = {
            int(_value(row, "id", 0, 0)): day_number
            for day_number, row in enumerate(reversed(attendance_rows), start=1)
        }

        attendance = []
        rendered_hours = 0.0
        completed_days = 0
        open_sessions = 0
        for row in attendance_rows:
            status = _value(row, "status", 4, "Open") or "Open"
            hours = _value(row, "hours_rendered", 3, None)
            try:
                hours_value = float(hours) if hours is not None else None
            except (TypeError, ValueError):
                hours_value = None
            if status == "Open":
                open_sessions += 1
            else:
                completed_days += 1
                if hours_value is not None:
                    rendered_hours += hours_value
            attendance.append(
                {
                    "id": int(_value(row, "id", 0, 0)),
                    "clock_in": _format_datetime(_value(row, "clock_in", 1, None)),
                    "clock_out": _format_datetime(_value(row, "clock_out", 2, None)) if _value(row, "clock_out", 2, None) else None,
                    "hours_rendered": hours_value,
                    "status": status,
                }
            )

        classroom = _classroom_dict(classroom_row)
        required_hours = classroom["required_hours"] if classroom["hours_mode"] == "specified" else None
        remaining_hours = None
        progress_percentage = None
        if required_hours and required_hours > 0:
            remaining_hours = max(required_hours - rendered_hours, 0.0)
            progress_percentage = min((rendered_hours / required_hours) * 100.0, 100.0)

        log_rows = conn.execute(
            """
            SELECT l.id, a.id AS attendance_id, a.clock_in, a.status,
                   COALESCE(l.accomplishment, l.content, '') AS accomplishment,
                   COALESCE(lr.status, '') AS review_status,
                   (SELECT COUNT(*) FROM logbook_photos lp WHERE lp.log_id = l.id) AS photo_count
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            LEFT JOIN logbook_reviews lr ON lr.log_id = l.id
            WHERE l.student_id = ?
              AND l.entry_type = 'daily'
              AND a.classroom_id = ?
            ORDER BY a.clock_in DESC, l.id DESC
            """,
            (student_id, classroom_id),
        ).fetchall()

        logbook_entries = []
        logbook_counts = {
            "total": 0,
            "pending": 0,
            "approved": 0,
            "revision_requested": 0,
            "reviewed": 0,
            "in_progress": 0,
        }
        for row in reversed(log_rows):
            attendance_id = int(_value(row, "attendance_id", 1, 0))
            attendance_status = _value(row, "status", 3, "Open") or "Open"
            stored_review_status = _value(row, "review_status", 5, "") or ""
            status = "in_progress" if attendance_status == "Open" else (stored_review_status or "pending")
            logbook_counts["total"] += 1
            if status in logbook_counts:
                logbook_counts[status] += 1
            logbook_entries.append(
                {
                    "id": int(_value(row, "id", 0, 0)),
                    "attendance_id": attendance_id,
                    "day_number": attendance_day_number_by_id.get(attendance_id),
                    "date": _format_date(_value(row, "clock_in", 2, None)),
                    "accomplishment": _value(row, "accomplishment", 4, "") or "",
                    "review_status": status,
                    "review_status_label": _review_label(status),
                    "photo_count": int(_value(row, "photo_count", 6, 0) or 0),
                }
            )
        logbook_entries.reverse()

        work_rows = conn.execute(
            """
            SELECT a.id, a.title, a.due_at, a.points, a.created_at,
                   s.score, s.max_score, s.percentage, s.grading_method
            FROM classroom_assignments a
            LEFT JOIN classwork_scores s
                   ON s.assignment_id = a.id
                  AND s.student_id = ?
            WHERE a.classroom_id = ?
              AND (
                    NOT EXISTS (
                        SELECT 1 FROM classroom_assignment_recipients car_all
                        WHERE car_all.assignment_id = a.id
                    )
                    OR EXISTS (
                        SELECT 1 FROM classroom_assignment_recipients car_student
                        WHERE car_student.assignment_id = a.id
                          AND car_student.student_id = ?
                    )
              )
            ORDER BY a.created_at DESC, a.id DESC
            """,
            (student_id, classroom_id, student_id),
        ).fetchall()

        work_items = []
        graded_percentages = []
        for row in work_rows:
            percentage = _safe_percentage(
                _value(row, "score", 5, None),
                _value(row, "max_score", 6, None),
                _value(row, "percentage", 7, None),
            )
            if percentage is not None:
                graded_percentages.append(percentage)
            work_items.append(
                {
                    "id": int(_value(row, "id", 0, 0)),
                    "title": _value(row, "title", 1, "Work") or "Work",
                    "due_at": _format_datetime(_value(row, "due_at", 2, None)) if _value(row, "due_at", 2, None) else None,
                    "points": _value(row, "points", 3, None),
                    "percentage": percentage,
                    "graded": percentage is not None,
                    "grading_method": _value(row, "grading_method", 8, None),
                }
            )

    finally:
        conn.close()

    daily_performance = get_supervisor_daily_performance_history(
        supervisor_id=supervisor_id,
        classroom_id=classroom_id,
        student_id=student_id,
    )
    if not daily_performance.get("ok"):
        daily_performance = {"history": [], "summary": {}}

    return {
        "ok": True,
        "status_code": 200,
        "classroom": classroom,
        "student": _student_dict(student_row),
        "attendance": attendance[:6],
        "attendance_summary": {
            "completed_days": completed_days,
            "open_sessions": open_sessions,
            "rendered_hours": round(rendered_hours, 2),
            "required_hours": required_hours,
            "remaining_hours": round(remaining_hours, 2) if remaining_hours is not None else None,
            "progress_percentage": round(progress_percentage, 1) if progress_percentage is not None else None,
        },
        "daily_performance": {
            "history": (daily_performance.get("history") or [])[-6:][::-1],
            "summary": daily_performance.get("summary") or {},
        },
        "logbook_entries": logbook_entries[:6],
        "logbook_summary": logbook_counts,
        "work_items": work_items[:6],
        "work_summary": {
            "assigned_count": len(work_items),
            "graded_count": len(graded_percentages),
            "average_percentage": round(sum(graded_percentages) / len(graded_percentages), 1) if graded_percentages else None,
        },
    }