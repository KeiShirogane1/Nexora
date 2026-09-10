"""Read-only classroom roster data for supervisor Intern Classroom views."""

from app.Models.db import get_db_connection


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


def _display_name(row):
    first_name = str(_value(row, "first_name", 3, "") or "").strip()
    middle_name = str(_value(row, "middle_name", 4, "") or "").strip()
    last_name = str(_value(row, "last_name", 5, "") or "").strip()
    username = str(_value(row, "username", 1, "") or "").strip()
    parts = [part for part in (first_name, middle_name, last_name) if part]
    return " ".join(parts) if parts else username or "Intern"


def get_supervisor_classroom_roster(supervisor_id, classroom_id):
    """Return classroom-scoped roster metrics without using legacy internship matching."""
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
    except (TypeError, ValueError):
        return {"ok": False, "status_code": 404, "students": []}

    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """
            SELECT c.id,
                   COALESCE(cid.hours_mode, 'not_specified') AS hours_mode,
                   COALESCE(cid.required_hours, 0) AS required_hours
            FROM classrooms c
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.id = ? AND c.supervisor_id = ?
            LIMIT 1
            """,
            (classroom_id, supervisor_id),
        ).fetchone()
        if not classroom:
            exists = conn.execute(
                "SELECT 1 FROM classrooms WHERE id = ?",
                (classroom_id,),
            ).fetchone()
            return {
                "ok": False,
                "status_code": 403 if exists else 404,
                "students": [],
            }

        hours_mode = str(_value(classroom, "hours_mode", 1, "not_specified") or "not_specified")
        try:
            configured_required_hours = float(_value(classroom, "required_hours", 2, 0) or 0)
        except (TypeError, ValueError):
            configured_required_hours = 0.0
        required_hours = (
            configured_required_hours
            if hours_mode == "specified" and configured_required_hours > 0
            else None
        )

        rows = conn.execute(
            """
            SELECT
                u.id,
                u.username,
                u.email,
                COALESCE(sp.first_name, '') AS first_name,
                COALESCE(sp.middle_name, '') AS middle_name,
                COALESCE(sp.last_name, '') AS last_name,
                COALESCE(sp.student_id, '') AS student_number,
                COALESCE(sp.major_program, '') AS major_program,
                COALESCE(sp.grade_year, '') AS grade_year,
                COALESCE(sp.profile_completed, 0) AS profile_completed,
                cs.joined_at,
                COALESCE((
                    SELECT SUM(a.hours_rendered)
                    FROM attendance a
                    WHERE a.classroom_id = ?
                      AND a.student_id = u.id
                      AND a.status = 'Completed'
                ), 0) AS rendered_hours,
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM attendance a_open
                    WHERE a_open.classroom_id = ?
                      AND a_open.student_id = u.id
                      AND a_open.status = 'Open'
                ) THEN 1 ELSE 0 END AS has_open_attendance,
                (
                    SELECT AVG(dpr.star_rating)
                    FROM daily_performance_ratings dpr
                    JOIN attendance a_rating ON a_rating.id = dpr.attendance_id
                    WHERE a_rating.classroom_id = ?
                      AND a_rating.student_id = u.id
                      AND dpr.supervisor_id = ?
                ) AS daily_average_star,
                (
                    SELECT AVG(dpr.percentage)
                    FROM daily_performance_ratings dpr
                    JOIN attendance a_rating ON a_rating.id = dpr.attendance_id
                    WHERE a_rating.classroom_id = ?
                      AND a_rating.student_id = u.id
                      AND dpr.supervisor_id = ?
                ) AS daily_average_percentage,
                (
                    SELECT COUNT(*)
                    FROM daily_performance_ratings dpr
                    JOIN attendance a_rating ON a_rating.id = dpr.attendance_id
                    WHERE a_rating.classroom_id = ?
                      AND a_rating.student_id = u.id
                      AND dpr.supervisor_id = ?
                ) AS rated_days,
                (
                    SELECT COUNT(*)
                    FROM logs l
                    JOIN attendance a_log ON a_log.id = l.attendance_id
                    WHERE l.student_id = u.id
                      AND l.entry_type = 'daily'
                      AND a_log.classroom_id = ?
                ) AS logbook_count,
                (
                    SELECT COUNT(*)
                    FROM logs l
                    JOIN attendance a_log ON a_log.id = l.attendance_id
                    LEFT JOIN logbook_reviews lr ON lr.log_id = l.id
                    WHERE l.student_id = u.id
                      AND l.entry_type = 'daily'
                      AND a_log.classroom_id = ?
                      AND a_log.status <> 'Open'
                      AND COALESCE(lr.status, 'pending') = 'pending'
                ) AS pending_logbook_count,
                (
                    SELECT COUNT(*)
                    FROM logs l
                    JOIN attendance a_log ON a_log.id = l.attendance_id
                    JOIN logbook_reviews lr ON lr.log_id = l.id
                    WHERE l.student_id = u.id
                      AND l.entry_type = 'daily'
                      AND a_log.classroom_id = ?
                      AND lr.status = 'revision_requested'
                ) AS revision_logbook_count
            FROM classroom_students cs
            JOIN users u ON u.id = cs.student_id
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE cs.classroom_id = ?
            ORDER BY
                LOWER(COALESCE(NULLIF(sp.first_name, ''), u.username)),
                LOWER(COALESCE(NULLIF(sp.last_name, ''), u.email)),
                u.id
            """,
            (
                classroom_id,
                classroom_id,
                classroom_id,
                supervisor_id,
                classroom_id,
                supervisor_id,
                classroom_id,
                supervisor_id,
                classroom_id,
                classroom_id,
                classroom_id,
                classroom_id,
            ),
        ).fetchall()

        students = []
        for row in rows:
            try:
                rendered_hours = float(_value(row, "rendered_hours", 11, 0) or 0)
            except (TypeError, ValueError):
                rendered_hours = 0.0
            has_open_attendance = bool(_value(row, "has_open_attendance", 12, 0))

            progress_percentage = None
            remaining_hours = None
            if required_hours is not None:
                progress_percentage = min((rendered_hours / required_hours) * 100.0, 100.0)
                remaining_hours = max(required_hours - rendered_hours, 0.0)

            if has_open_attendance:
                roster_status = "Clocked In"
                roster_status_key = "active"
            elif required_hours is not None and rendered_hours >= required_hours:
                roster_status = "Hours Complete"
                roster_status_key = "completed"
            else:
                roster_status = "Enrolled"
                roster_status_key = "enrolled"

            daily_average_star = _value(row, "daily_average_star", 13, None)
            daily_average_percentage = _value(row, "daily_average_percentage", 14, None)
            try:
                daily_average_star = float(daily_average_star) if daily_average_star is not None else None
            except (TypeError, ValueError):
                daily_average_star = None
            try:
                daily_average_percentage = float(daily_average_percentage) if daily_average_percentage is not None else None
            except (TypeError, ValueError):
                daily_average_percentage = None

            students.append(
                {
                    "id": int(_value(row, "id", 0, 0)),
                    "username": _value(row, "username", 1, "") or "",
                    "email_address": _value(row, "email", 2, "") or "",
                    "display_name": _display_name(row),
                    "student_number": _value(row, "student_number", 6, "") or "",
                    "major_program": _value(row, "major_program", 7, "") or "",
                    "grade_year": _value(row, "grade_year", 8, "") or "",
                    "profile_completed": bool(_value(row, "profile_completed", 9, 0)),
                    "joined_at": _value(row, "joined_at", 10, None),
                    "rendered_hours": round(rendered_hours, 2),
                    "required_hours": required_hours,
                    "remaining_hours": round(remaining_hours, 2) if remaining_hours is not None else None,
                    "progress_percentage": round(progress_percentage, 1) if progress_percentage is not None else None,
                    "has_open_attendance": has_open_attendance,
                    "roster_status": roster_status,
                    "roster_status_key": roster_status_key,
                    "daily_average_star": round(daily_average_star, 1) if daily_average_star is not None else None,
                    "daily_average_percentage": round(daily_average_percentage, 1) if daily_average_percentage is not None else None,
                    "rated_days": int(_value(row, "rated_days", 15, 0) or 0),
                    "logbook_count": int(_value(row, "logbook_count", 16, 0) or 0),
                    "pending_logbook_count": int(_value(row, "pending_logbook_count", 17, 0) or 0),
                    "revision_logbook_count": int(_value(row, "revision_logbook_count", 18, 0) or 0),
                }
            )

        return {
            "ok": True,
            "status_code": 200,
            "students": students,
            "required_hours": required_hours,
        }
    finally:
        conn.close()
