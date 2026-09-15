"""Intern Classroom weekly schedule helpers.

The weekly schedule is additive. Legacy start/end date columns remain intact so
existing classrooms keep their historical data while new/edited Intern
Classrooms can use repeatable attendance days and shift times.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from app.Models.db import get_db_connection, using_postgres
from app.Services.notification_service import create_notification

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_ATTENDANCE_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat")
DEFAULT_START_TIME = "09:00"
DEFAULT_END_TIME = "17:00"
DEFAULT_HOURS_PER_DAY = 8
APP_TIMEZONE = os.environ.get("NEXORA_TIMEZONE", "Asia/Manila")
_SCHEMA_READY = False


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


def app_local_now(now=None):
    """Return an application-local naive datetime for schedule comparisons."""
    if now is None:
        return datetime.now(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None)
    if now.tzinfo is not None:
        return now.astimezone(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None)
    return now


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def attendance_local_datetime(raw_value, server_to_local_offset=None):
    """Normalize a stored attendance timestamp to Nexora's configured local time."""
    value = _parse_datetime(raw_value)
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None)
    if server_to_local_offset is None:
        server_to_local_offset = app_local_now() - datetime.now()
    return value + server_to_local_offset


def _parse_time(value, fallback):
    raw = str(value or fallback).strip()
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except (TypeError, ValueError):
        return datetime.strptime(fallback, "%H:%M").time()


def normalize_attendance_days(values):
    if isinstance(values, str):
        values = values.split(",")
    selected = []
    for value in values or []:
        key = str(value or "").strip().lower()[:3]
        if key in WEEKDAYS and key not in selected:
            selected.append(key)
    return [day for day in WEEKDAYS if day in selected]


def attendance_days_text(values):
    return ",".join(normalize_attendance_days(values))


def ensure_internship_schedule_schema():
    """Add weekly schedule fields once per process without rewriting legacy data."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    conn = get_db_connection()
    try:
        if using_postgres():
            statements = [
                "ALTER TABLE classroom_internship_details ADD COLUMN IF NOT EXISTS program TEXT",
                "ALTER TABLE classroom_internship_details ADD COLUMN IF NOT EXISTS hours_per_day INTEGER NOT NULL DEFAULT 8",
                "ALTER TABLE classroom_internship_details ADD COLUMN IF NOT EXISTS required_days INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE classroom_internship_details ADD COLUMN IF NOT EXISTS attendance_days TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat'",
                "ALTER TABLE classroom_internship_details ADD COLUMN IF NOT EXISTS shift_start_time TEXT NOT NULL DEFAULT '09:00'",
                "ALTER TABLE classroom_internship_details ADD COLUMN IF NOT EXISTS shift_end_time TEXT NOT NULL DEFAULT '17:00'",
            ]
            for statement in statements:
                conn.execute(statement)
        else:
            columns = [
                row[1]
                for row in conn.execute("PRAGMA table_info(classroom_internship_details)").fetchall()
            ]
            additions = {
                "program": "TEXT",
                "hours_per_day": "INTEGER NOT NULL DEFAULT 8",
                "required_days": "INTEGER NOT NULL DEFAULT 0",
                "attendance_days": "TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat'",
                "shift_start_time": "TEXT NOT NULL DEFAULT '09:00'",
                "shift_end_time": "TEXT NOT NULL DEFAULT '17:00'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE classroom_internship_details ADD COLUMN {name} {definition}")
        conn.commit()
        _SCHEMA_READY = True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _resolve_student_classroom(conn, student_id, classroom_id=None):
    if classroom_id not in (None, ""):
        try:
            classroom_id = int(classroom_id)
        except (TypeError, ValueError):
            return None
        row = conn.execute(
            """
            SELECT c.id
            FROM classroom_students cs
            JOIN classrooms c ON c.id = cs.classroom_id
            WHERE cs.student_id = ? AND c.id = ?
              AND COALESCE(c.archived, 0) = 0
              AND COALESCE(c.classroom_type, 'classroom') = 'internship'
            LIMIT 1
            """,
            (student_id, classroom_id),
        ).fetchone()
        return int(_row_value(row, "id", 0, 0)) if row else None

    rows = conn.execute(
        """
        SELECT c.id
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        WHERE cs.student_id = ?
          AND COALESCE(c.archived, 0) = 0
          AND COALESCE(c.classroom_type, 'classroom') = 'internship'
        ORDER BY cs.joined_at DESC, c.id DESC
        """,
        (student_id,),
    ).fetchall()
    if len(rows) != 1:
        return None
    return int(_row_value(rows[0], "id", 0, 0))


def _student_progress(conn, student_id, classroom_id, server_to_local_offset=None):
    rows = conn.execute(
        """
        SELECT clock_in, COALESCE(hours_rendered, 0) AS hours_rendered
        FROM attendance
        WHERE student_id = ? AND classroom_id = ? AND status = 'Completed'
        ORDER BY clock_in ASC, id ASC
        """,
        (student_id, classroom_id),
    ).fetchall()

    rendered_hours = 0.0
    completed_dates = set()
    for row in rows:
        try:
            rendered_hours += float(_row_value(row, "hours_rendered", 1, 0) or 0)
        except (TypeError, ValueError):
            pass
        local_clock = attendance_local_datetime(
            _row_value(row, "clock_in", 0, None),
            server_to_local_offset=server_to_local_offset,
        )
        if local_clock is not None:
            completed_dates.add(local_clock.date())

    return {
        "rendered_hours": rendered_hours,
        "completed_days": len(completed_dates),
    }


def _schedule_is_complete(progress, required_days, required_hours):
    checks = []
    if required_days > 0:
        checks.append(progress["completed_days"] >= required_days)
    if required_hours > 0:
        checks.append(progress["rendered_hours"] >= required_hours)
    return bool(checks and all(checks))


def get_student_schedule_state(student_id, classroom_id=None, now=None):
    """Return schedule, attendance-day integrity, and sidebar attention state."""
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return {"classroom_id": None, "attention_count": 0, "attention_reason": None}

    try:
        ensure_internship_schedule_schema()
    except Exception:
        return {"classroom_id": None, "attention_count": 0, "attention_reason": None}

    current = app_local_now(now)
    # Existing attendance rows use the application's historical naive server clock.
    # Detect the server-to-Nexora offset instead of rewriting those rows.
    server_now = current if now is not None else datetime.now()
    server_to_local_offset = current - server_now

    conn = get_db_connection()
    try:
        resolved_classroom_id = _resolve_student_classroom(conn, student_id, classroom_id)
        if not resolved_classroom_id:
            return {"classroom_id": None, "attention_count": 0, "attention_reason": None}

        details = conn.execute(
            """
            SELECT COALESCE(schedule_type, 'not_specified') AS schedule_type,
                   COALESCE(hours_per_day, 8) AS hours_per_day,
                   COALESCE(required_days, 0) AS required_days,
                   COALESCE(required_hours, 0) AS required_hours,
                   COALESCE(attendance_days, 'mon,tue,wed,thu,fri,sat') AS attendance_days,
                   COALESCE(shift_start_time, '09:00') AS shift_start_time,
                   COALESCE(shift_end_time, '17:00') AS shift_end_time
            FROM classroom_internship_details
            WHERE classroom_id = ?
            LIMIT 1
            """,
            (resolved_classroom_id,),
        ).fetchone()

        schedule_type = str(_row_value(details, "schedule_type", 0, "not_specified") or "not_specified").lower()
        hours_per_day = int(_row_value(details, "hours_per_day", 1, DEFAULT_HOURS_PER_DAY) or DEFAULT_HOURS_PER_DAY)
        required_days = int(_row_value(details, "required_days", 2, 0) or 0)
        required_hours = float(_row_value(details, "required_hours", 3, 0) or 0)
        attendance_days = normalize_attendance_days(
            _row_value(details, "attendance_days", 4, ",".join(DEFAULT_ATTENDANCE_DAYS))
        )
        shift_start_raw = str(_row_value(details, "shift_start_time", 5, DEFAULT_START_TIME) or DEFAULT_START_TIME)
        shift_end_raw = str(_row_value(details, "shift_end_time", 6, DEFAULT_END_TIME) or DEFAULT_END_TIME)
        shift_start = _parse_time(shift_start_raw, DEFAULT_START_TIME)
        shift_end = _parse_time(shift_end_raw, DEFAULT_END_TIME)

        progress = _student_progress(
            conn,
            student_id,
            resolved_classroom_id,
            server_to_local_offset=server_to_local_offset,
        )
        schedule_complete = _schedule_is_complete(progress, required_days, required_hours)

        weekday = WEEKDAYS[current.weekday()]
        is_scheduled_day = schedule_type != "weekly" or weekday in attendance_days
        state = {
            "classroom_id": resolved_classroom_id,
            "schedule_type": schedule_type,
            "hours_per_day": hours_per_day,
            "required_days": required_days,
            "required_hours": required_hours,
            "attendance_days": attendance_days,
            "shift_start_time": shift_start_raw,
            "shift_end_time": shift_end_raw,
            "completed_days": progress["completed_days"],
            "rendered_hours": round(progress["rendered_hours"], 2),
            "schedule_complete": schedule_complete,
            "attention_count": 0,
            "attention_reason": None,
            "seconds_until_attention": None,
            "is_scheduled_day": is_scheduled_day,
            "has_open_attendance": False,
            "has_attendance_today": False,
            "completed_today": False,
            "can_clock_in": True,
            "clock_in_block_reason": None,
        }

        recent_attendance = conn.execute(
            """
            SELECT id, clock_in, status
            FROM attendance
            WHERE student_id = ? AND classroom_id = ?
            ORDER BY clock_in DESC, id DESC
            LIMIT 10
            """,
            (student_id, resolved_classroom_id),
        ).fetchall()
        for row in recent_attendance:
            local_clock = attendance_local_datetime(
                _row_value(row, "clock_in", 1, None),
                server_to_local_offset=server_to_local_offset,
            )
            if local_clock is None or local_clock.date() != current.date():
                continue
            state["has_attendance_today"] = True
            if str(_row_value(row, "status", 2, "") or "") == "Completed":
                state["completed_today"] = True

        open_attendance = conn.execute(
            """
            SELECT id, clock_in
            FROM attendance
            WHERE student_id = ? AND classroom_id = ? AND status = 'Open'
            ORDER BY clock_in DESC
            LIMIT 1
            """,
            (student_id, resolved_classroom_id),
        ).fetchone()

        if open_attendance:
            state["has_open_attendance"] = True
            state["can_clock_in"] = False
            state["clock_in_block_reason"] = "An OJT attendance session is already active."
            if schedule_type != "weekly":
                return state

            today_end = datetime.combine(current.date(), shift_end)
            attendance_id = int(_row_value(open_attendance, "id", 0, 0) or 0)
            raw_clock_in = _row_value(open_attendance, "clock_in", 1, None)
            clock_in_server = _parse_datetime(raw_clock_in)
            if clock_in_server is None:
                elapsed_seconds = 0
            elif clock_in_server.tzinfo is not None:
                elapsed_seconds = max(
                    0,
                    (
                        datetime.now(ZoneInfo(APP_TIMEZONE))
                        - clock_in_server.astimezone(ZoneInfo(APP_TIMEZONE))
                    ).total_seconds(),
                )
            else:
                elapsed_seconds = max(0, (server_now - clock_in_server).total_seconds())

            seconds_until_daily_target = max(0, (hours_per_day * 3600) - elapsed_seconds)
            seconds_until_shift_end = max(0, (today_end - current).total_seconds())
            due_now = current >= today_end or elapsed_seconds >= (hours_per_day * 3600)

            if due_now:
                daily_log = conn.execute(
                    """
                    SELECT 1 FROM logs
                    WHERE attendance_id = ? AND student_id = ? AND entry_type = 'daily'
                    LIMIT 1
                    """,
                    (attendance_id, student_id),
                ).fetchone()
                state["attention_count"] = 1
                state["attention_reason"] = "clock_out" if daily_log else "logbook_and_clock_out"
            else:
                state["seconds_until_attention"] = int(
                    min(seconds_until_daily_target, seconds_until_shift_end)
                )
            return state

        if schedule_complete:
            state["can_clock_in"] = False
            state["clock_in_block_reason"] = "Your configured OJT attendance requirements are already complete."
            return state

        if schedule_type == "weekly" and not is_scheduled_day:
            state["can_clock_in"] = False
            state["clock_in_block_reason"] = "Today is not a scheduled OJT attendance day."
            return state

        if state["has_attendance_today"]:
            state["can_clock_in"] = False
            if state["completed_today"]:
                state["clock_in_block_reason"] = (
                    "Today's OJT attendance is already completed. Clock In will be available on your next OJT day."
                )
            else:
                state["clock_in_block_reason"] = "Today's OJT attendance has already been recorded."
            return state

        if schedule_type != "weekly":
            return state

        today_start = datetime.combine(current.date(), shift_start)
        if current >= today_start:
            state["attention_count"] = 1
            state["attention_reason"] = "check_in"
        else:
            state["seconds_until_attention"] = max(
                0,
                int((today_start - current).total_seconds()),
            )
        return state
    finally:
        conn.close()


def _notification_exists(user_id, title, link_url):
    conn = get_db_connection()
    try:
        return conn.execute(
            """
            SELECT 1 FROM notifications
            WHERE user_id = ? AND title = ? AND COALESCE(link_url, '') = ?
            LIMIT 1
            """,
            (user_id, title, link_url or ""),
        ).fetchone() is not None
    finally:
        conn.close()


def ensure_supervisor_completion_notifications(supervisor_id):
    """Notify once a weekly Intern Classroom is ready for formal evaluations."""
    try:
        supervisor_id = int(supervisor_id)
    except (TypeError, ValueError):
        return 0

    try:
        ensure_internship_schedule_schema()
    except Exception:
        return 0

    candidates = []
    conn = get_db_connection()
    try:
        classrooms = conn.execute(
            """
            SELECT c.id, c.name,
                   COALESCE(cid.required_days, 0) AS required_days,
                   COALESCE(cid.required_hours, 0) AS required_hours,
                   COALESCE(cid.schedule_type, 'not_specified') AS schedule_type
            FROM classrooms c
            JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.supervisor_id = ? AND COALESCE(c.archived, 0) = 0
              AND COALESCE(c.classroom_type, 'classroom') = 'internship'
            """,
            (supervisor_id,),
        ).fetchall()

        for classroom in classrooms:
            class_id = int(_row_value(classroom, "id", 0, 0) or 0)
            class_name = str(_row_value(classroom, "name", 1, "Intern Classroom") or "Intern Classroom")
            required_days = int(_row_value(classroom, "required_days", 2, 0) or 0)
            required_hours = float(_row_value(classroom, "required_hours", 3, 0) or 0)
            schedule_type = str(_row_value(classroom, "schedule_type", 4, "not_specified") or "not_specified").lower()
            if schedule_type != "weekly" or required_days <= 0 or required_hours <= 0:
                continue

            students = conn.execute(
                "SELECT student_id FROM classroom_students WHERE classroom_id = ?",
                (class_id,),
            ).fetchall()
            if not students:
                continue

            pending_evaluations = 0
            all_complete = True
            for student in students:
                student_id = int(_row_value(student, "student_id", 0, 0) or 0)
                progress = _student_progress(conn, student_id, class_id)
                if progress["completed_days"] < required_days or progress["rendered_hours"] < required_hours:
                    all_complete = False
                    break
                evaluation = conn.execute(
                    """
                    SELECT status FROM ojt_evaluations
                    WHERE classroom_id = ? AND student_id = ? AND supervisor_id = ?
                    LIMIT 1
                    """,
                    (class_id, student_id, supervisor_id),
                ).fetchone()
                if str(_row_value(evaluation, "status", 0, "") or "").lower() != "submitted":
                    pending_evaluations += 1

            if all_complete and pending_evaluations > 0:
                candidates.append((class_id, class_name, pending_evaluations))
    finally:
        conn.close()

    created = 0
    for class_id, class_name, pending_evaluations in candidates:
        title = "Official OJT Evaluation Ready"
        link_url = f"/supervisor/evaluations?class_id={class_id}"
        if _notification_exists(supervisor_id, title, link_url):
            continue
        try:
            create_notification(
                supervisor_id,
                title,
                f"{class_name} has completed its configured OJT schedule. Evaluate {pending_evaluations} intern{'s' if pending_evaluations != 1 else ''} in Official OJT Evaluation.",
                "warning",
                link_url=link_url,
            )
            created += 1
        except Exception:
            # Notification delivery should never block normal Supervisor requests.
            continue
    return created
