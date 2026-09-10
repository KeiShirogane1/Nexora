"""Read-only daily OJT performance history for supervisor classroom views."""
from datetime import datetime

from app.Models.db import get_db_connection


def _row_value(row, key, index=0, default=None):
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


def _format_date(value):
    parsed = _as_datetime(value)
    return parsed.strftime("%b %d, %Y") if parsed else "—"


def _student_display_name(row):
    first_name = (_row_value(row, "first_name", 3, "") or "").strip()
    last_name = (_row_value(row, "last_name", 4, "") or "").strip()
    username = (_row_value(row, "username", 1, "") or "").strip()
    email = (_row_value(row, "email", 2, "") or "").strip()
    return " ".join(part for part in (first_name, last_name) if part).strip() or username or email or "Intern"


def _classroom_dict(row):
    if not row:
        return None
    return {
        "id": int(_row_value(row, "id", 0, 0)),
        "name": _row_value(row, "name", 1, "Intern Classroom"),
        "section": _row_value(row, "section", 2, ""),
        "description": _row_value(row, "description", 3, ""),
        "code": _row_value(row, "code", 4, ""),
        "archived": bool(_row_value(row, "archived", 5, 0)),
        "company_name": _row_value(row, "company_name", 6, ""),
    }


def _can_use_legacy_attendance(conn, student_id, classroom_id):
    """Use unscoped legacy attendance only when the classroom relationship is unambiguous."""
    rows = conn.execute(
        """
        SELECT c.id
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        WHERE cs.student_id = ?
          AND COALESCE(c.classroom_type, 'classroom') = 'internship'
        ORDER BY c.id
        """,
        (student_id,),
    ).fetchall()
    classroom_ids = [int(_row_value(row, "id", 0, 0)) for row in rows]
    return len(classroom_ids) == 1 and classroom_ids[0] == int(classroom_id)


def _attendance_history_rows(conn, supervisor_id, classroom_id, student_id):
    base_select = """
        SELECT a.id AS attendance_id, a.clock_in, a.status,
               l.id AS log_id,
               dpr.star_rating, dpr.percentage, dpr.comment,
               dpr.rated_at, dpr.updated_at
        FROM attendance a
        LEFT JOIN logs l
               ON l.attendance_id = a.id
              AND l.student_id = a.student_id
              AND l.entry_type = 'daily'
        LEFT JOIN daily_performance_ratings dpr
               ON dpr.attendance_id = a.id
              AND dpr.supervisor_id = ?
    """

    scoped_rows = conn.execute(
        base_select
        + """
        WHERE a.classroom_id = ?
          AND a.student_id = ?
        ORDER BY a.clock_in ASC, a.id ASC
        """,
        (supervisor_id, classroom_id, student_id),
    ).fetchall()
    if scoped_rows:
        return scoped_rows

    if not _can_use_legacy_attendance(conn, student_id, classroom_id):
        return []

    return conn.execute(
        base_select
        + """
        WHERE a.classroom_id IS NULL
          AND a.student_id = ?
        ORDER BY a.clock_in ASC, a.id ASC
        """,
        (supervisor_id, student_id),
    ).fetchall()


def get_supervisor_daily_performance_history(supervisor_id, classroom_id, student_id=None):
    """Return one owned classroom roster and one intern's manual daily rating history."""
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
        student_id = int(student_id) if student_id is not None else None
    except (TypeError, ValueError):
        return {"ok": False, "status_code": 404}

    conn = get_db_connection()
    try:
        classroom_row = conn.execute(
            """
            SELECT c.id, c.name, c.section, c.description, c.code, c.archived,
                   COALESCE(cid.company_name, '') AS company_name
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

        roster_rows = conn.execute(
            """
            SELECT u.id, u.username, u.email,
                   COALESCE(sp.first_name, '') AS first_name,
                   COALESCE(sp.last_name, '') AS last_name
            FROM classroom_students cs
            JOIN users u ON u.id = cs.student_id
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE cs.classroom_id = ?
            ORDER BY LOWER(COALESCE(NULLIF(sp.first_name, ''), u.username)),
                     LOWER(COALESCE(NULLIF(sp.last_name, ''), u.email)),
                     u.id
            """,
            (classroom_id,),
        ).fetchall()
        roster = [
            {
                "id": int(_row_value(row, "id", 0, 0)),
                "username": _row_value(row, "username", 1, ""),
                "email": _row_value(row, "email", 2, "") or "",
                "display_name": _student_display_name(row),
            }
            for row in roster_rows
        ]

        selected_student = None
        if roster:
            if student_id is None:
                selected_student = roster[0]
            else:
                selected_student = next((student for student in roster if student["id"] == student_id), None)
                if selected_student is None:
                    return {"ok": False, "status_code": 404}

        history = []
        summary = {
            "closed_days": 0,
            "rated_days": 0,
            "average_star": None,
            "average_percentage": None,
            "latest_star": None,
            "latest_percentage": None,
            "highest_percentage": None,
            "lowest_percentage": None,
            "latest_trend_direction": "baseline",
            "latest_trend_delta": None,
        }

        if selected_student:
            attendance_rows = _attendance_history_rows(
                conn,
                supervisor_id,
                classroom_id,
                selected_student["id"],
            )

            previous_rated_percentage = None
            rated_stars = []
            rated_percentages = []
            for day_number, row in enumerate(attendance_rows, start=1):
                attendance_status = _row_value(row, "status", 2, "Open") or "Open"
                if attendance_status == "Open":
                    continue

                raw_star = _row_value(row, "star_rating", 4, None)
                raw_percentage = _row_value(row, "percentage", 5, None)
                is_rated = raw_star is not None and raw_percentage is not None
                star_rating = float(raw_star) if is_rated else None
                percentage = float(raw_percentage) if is_rated else None
                trend_direction = "unrated"
                trend_delta = None

                if is_rated:
                    rated_stars.append(star_rating)
                    rated_percentages.append(percentage)
                    if previous_rated_percentage is None:
                        trend_direction = "baseline"
                    else:
                        trend_delta = round(percentage - previous_rated_percentage, 1)
                        if trend_delta > 0:
                            trend_direction = "up"
                        elif trend_delta < 0:
                            trend_direction = "down"
                        else:
                            trend_direction = "same"
                    previous_rated_percentage = percentage

                history.append(
                    {
                        "attendance_id": int(_row_value(row, "attendance_id", 0, 0)),
                        "log_id": _row_value(row, "log_id", 3, None),
                        "day_number": day_number,
                        "date": _format_date(_row_value(row, "clock_in", 1, None)),
                        "is_rated": is_rated,
                        "star_rating": star_rating,
                        "percentage": percentage,
                        "comment": _row_value(row, "comment", 6, "") or "",
                        "rated_at": _row_value(row, "rated_at", 7, None),
                        "updated_at": _row_value(row, "updated_at", 8, None),
                        "trend_direction": trend_direction,
                        "trend_delta": trend_delta,
                    }
                )

            summary["closed_days"] = len(history)
            summary["rated_days"] = len(rated_percentages)
            if rated_percentages:
                summary["average_star"] = round(sum(rated_stars) / len(rated_stars), 1)
                summary["average_percentage"] = round(sum(rated_percentages) / len(rated_percentages), 1)
                summary["latest_star"] = rated_stars[-1]
                summary["latest_percentage"] = rated_percentages[-1]
                summary["highest_percentage"] = max(rated_percentages)
                summary["lowest_percentage"] = min(rated_percentages)
                latest_rated = next((item for item in reversed(history) if item["is_rated"]), None)
                if latest_rated:
                    summary["latest_trend_direction"] = latest_rated["trend_direction"]
                    summary["latest_trend_delta"] = latest_rated["trend_delta"]

        return {
            "ok": True,
            "status_code": 200,
            "classroom": _classroom_dict(classroom_row),
            "roster": roster,
            "selected_student": selected_student,
            "history": history,
            "summary": summary,
        }
    finally:
        conn.close()
