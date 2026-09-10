"""Structured Daily OJT Logbook helpers."""
from datetime import datetime

from app.Models.db import get_db_connection, using_postgres


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
    dt = _as_datetime(value)
    return dt.strftime("%b %d, %Y") if dt else "—"


def _format_time(value):
    dt = _as_datetime(value)
    return dt.strftime("%I:%M %p").lstrip("0") if dt else None


def ensure_logbook_schema():
    """Extend legacy logs without rewriting or deleting existing activity rows."""
    conn = get_db_connection()
    try:
        if using_postgres():
            statements = [
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS entry_type TEXT NOT NULL DEFAULT 'activity'",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS accomplishment TEXT",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS reflection TEXT",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS challenges TEXT",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS related_assignment_id INTEGER REFERENCES classroom_assignments(id) ON DELETE SET NULL",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
            ]
            for statement in statements:
                conn.execute(statement)
        else:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(logs)").fetchall()]
            additions = {
                "entry_type": "TEXT NOT NULL DEFAULT 'activity'",
                "accomplishment": "TEXT",
                "reflection": "TEXT",
                "challenges": "TEXT",
                "related_assignment_id": "INTEGER REFERENCES classroom_assignments(id) ON DELETE SET NULL",
                "updated_at": "TIMESTAMP",
            }
            for name, definition in additions.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE logs ADD COLUMN {name} {definition}")

        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_logs_student_daily
               ON logs(student_id, entry_type, created_at)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_logs_related_assignment
               ON logs(related_assignment_id)"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_logs_daily_attendance_unique
               ON logs(attendance_id)
               WHERE entry_type = 'daily'"""
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _visible_work(conn, student_id, classroom_id):
    if not classroom_id:
        return []
    rows = conn.execute(
        """
        SELECT a.id, a.title
        FROM classroom_assignments a
        WHERE a.classroom_id = ?
          AND (
                NOT EXISTS (
                    SELECT 1
                    FROM classroom_assignment_recipients r
                    WHERE r.assignment_id = a.id
                )
                OR EXISTS (
                    SELECT 1
                    FROM classroom_assignment_recipients r
                    WHERE r.assignment_id = a.id
                      AND r.student_id = ?
                )
          )
        ORDER BY a.created_at DESC, a.id DESC
        """,
        (classroom_id, student_id),
    ).fetchall()
    return [
        {
            "id": int(_row_value(row, "id", 0, 0)),
            "title": _row_value(row, "title", 1, "Work"),
        }
        for row in rows
    ]


def _attendance_day_map(conn, student_id, classroom_id):
    if classroom_id is None:
        rows = conn.execute(
            """
            SELECT id
            FROM attendance
            WHERE student_id = ? AND classroom_id IS NULL
            ORDER BY clock_in ASC, id ASC
            """,
            (student_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id
            FROM attendance
            WHERE student_id = ? AND classroom_id = ?
            ORDER BY clock_in ASC, id ASC
            """,
            (student_id, classroom_id),
        ).fetchall()
    return {
        int(_row_value(row, "id", 0, 0)): index + 1
        for index, row in enumerate(rows)
    }


def _serialize_daily_row(row, day_map):
    attendance_id = int(_row_value(row, "attendance_id", 1, 0))
    hours = _row_value(row, "hours_rendered", 11, None)
    try:
        hours = float(hours) if hours is not None else None
    except (TypeError, ValueError):
        hours = None
    return {
        "id": int(_row_value(row, "id", 0, 0)),
        "attendance_id": attendance_id,
        "day_number": day_map.get(attendance_id),
        "accomplishment": _row_value(row, "accomplishment", 2, "") or "",
        "reflection": _row_value(row, "reflection", 3, "") or "",
        "challenges": _row_value(row, "challenges", 4, "") or "",
        "related_assignment_id": _row_value(row, "related_assignment_id", 5, None),
        "related_work_title": _row_value(row, "related_work_title", 6, None),
        "created_at": _row_value(row, "created_at", 7, None),
        "updated_at": _row_value(row, "updated_at", 8, None),
        "date": _format_date(_row_value(row, "clock_in", 9, None)),
        "time_in": _format_time(_row_value(row, "clock_in", 9, None)),
        "time_out": _format_time(_row_value(row, "clock_out", 10, None)),
        "hours_rendered": hours,
        "status": _row_value(row, "status", 12, "Open"),
    }


def get_daily_logbook_context(student_id, classroom_id=None, attendance_id=None):
    """Return structured Daily OJT entries for one authorized intern/classroom scope."""
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return {"entries": [], "current_entry": None, "work_options": [], "total_entries": 0}

    normalized_classroom_id = None
    if classroom_id not in (None, ""):
        try:
            normalized_classroom_id = int(classroom_id)
        except (TypeError, ValueError):
            return {"entries": [], "current_entry": None, "work_options": [], "total_entries": 0}

    normalized_attendance_id = None
    if attendance_id not in (None, ""):
        try:
            normalized_attendance_id = int(attendance_id)
        except (TypeError, ValueError):
            normalized_attendance_id = None

    conn = get_db_connection()
    try:
        if normalized_classroom_id is not None:
            membership = conn.execute(
                """
                SELECT 1
                FROM classroom_students cs
                JOIN classrooms c ON c.id = cs.classroom_id
                WHERE cs.student_id = ?
                  AND cs.classroom_id = ?
                  AND COALESCE(c.classroom_type, 'classroom') = 'internship'
                LIMIT 1
                """,
                (student_id, normalized_classroom_id),
            ).fetchone()
            if not membership:
                return {"entries": [], "current_entry": None, "work_options": [], "total_entries": 0}
            scope_sql = "a.classroom_id = ?"
            scope_params = [normalized_classroom_id]
        else:
            scope_sql = "a.classroom_id IS NULL"
            scope_params = []

        day_map = _attendance_day_map(conn, student_id, normalized_classroom_id)
        rows = conn.execute(
            f"""
            SELECT
                l.id,
                l.attendance_id,
                l.accomplishment,
                l.reflection,
                l.challenges,
                l.related_assignment_id,
                ca.title AS related_work_title,
                l.created_at,
                l.updated_at,
                a.clock_in,
                a.clock_out,
                a.hours_rendered,
                a.status
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            LEFT JOIN classroom_assignments ca ON ca.id = l.related_assignment_id
            WHERE l.student_id = ?
              AND l.entry_type = 'daily'
              AND {scope_sql}
            ORDER BY a.clock_in DESC, l.id DESC
            """,
            tuple([student_id] + scope_params),
        ).fetchall()
        entries = [_serialize_daily_row(row, day_map) for row in rows]
        current_entry = next(
            (entry for entry in entries if entry["attendance_id"] == normalized_attendance_id),
            None,
        )
        return {
            "entries": entries,
            "current_entry": current_entry,
            "work_options": _visible_work(conn, student_id, normalized_classroom_id),
            "total_entries": len(entries),
        }
    finally:
        conn.close()


def get_session_daily_log(student_id, attendance_id):
    """Return one structured Daily OJT entry for a student-owned attendance session."""
    try:
        student_id = int(student_id)
        attendance_id = int(attendance_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        attendance = conn.execute(
            "SELECT classroom_id FROM attendance WHERE id = ? AND student_id = ?",
            (attendance_id, student_id),
        ).fetchone()
        if not attendance:
            return None
        classroom_id = _row_value(attendance, "classroom_id", 0, None)
        day_map = _attendance_day_map(conn, student_id, classroom_id)
        row = conn.execute(
            """
            SELECT
                l.id,
                l.attendance_id,
                l.accomplishment,
                l.reflection,
                l.challenges,
                l.related_assignment_id,
                ca.title AS related_work_title,
                l.created_at,
                l.updated_at,
                a.clock_in,
                a.clock_out,
                a.hours_rendered,
                a.status
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            LEFT JOIN classroom_assignments ca ON ca.id = l.related_assignment_id
            WHERE l.student_id = ?
              AND l.attendance_id = ?
              AND l.entry_type = 'daily'
            LIMIT 1
            """,
            (student_id, attendance_id),
        ).fetchone()
        return _serialize_daily_row(row, day_map) if row else None
    finally:
        conn.close()
