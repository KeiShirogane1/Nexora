"""Attendance helpers for Intern Classroom-scoped OJT sessions."""
from app.Models.db import get_db_connection, using_postgres


def ensure_attendance_schema():
    """Add classroom scope to attendance without rewriting legacy rows."""
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute(
                """ALTER TABLE attendance
                   ADD COLUMN IF NOT EXISTS classroom_id INTEGER
                   REFERENCES classrooms(id) ON DELETE SET NULL"""
            )
        else:
            columns = [
                row[1]
                for row in conn.execute("PRAGMA table_info(attendance)").fetchall()
            ]
            if "classroom_id" not in columns:
                conn.execute(
                    """ALTER TABLE attendance
                       ADD COLUMN classroom_id INTEGER
                       REFERENCES classrooms(id) ON DELETE SET NULL"""
                )

        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_attendance_student_classroom_status
               ON attendance(student_id, classroom_id, status)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_attendance_classroom_clock_in
               ON attendance(classroom_id, clock_in)"""
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


def get_ojt_progress(student_id, classroom_id):
    """Return verified, classroom-scoped OJT hour progress for one intern."""
    if not student_id or not classroom_id:
        return None

    try:
        student_id = int(student_id)
        classroom_id = int(classroom_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """
            SELECT
                COALESCE(cid.hours_mode, 'not_specified') AS hours_mode,
                COALESCE(cid.required_hours, 0) AS required_hours
            FROM classroom_students cs
            JOIN classrooms c ON c.id = cs.classroom_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE cs.student_id = ?
              AND c.id = ?
              AND c.archived = 0
              AND COALESCE(c.classroom_type, 'classroom') = 'internship'
            LIMIT 1
            """,
            (student_id, classroom_id),
        ).fetchone()
        if not classroom:
            return None

        hours_mode = classroom["hours_mode"] if "hours_mode" in classroom.keys() else classroom[0]
        required_hours = classroom["required_hours"] if "required_hours" in classroom.keys() else classroom[1]

        row = conn.execute(
            """
            SELECT COALESCE(SUM(hours_rendered), 0)
            FROM attendance
            WHERE student_id = ?
              AND classroom_id = ?
              AND status = 'Completed'
            """,
            (student_id, classroom_id),
        ).fetchone()
        rendered_hours = float(row[0] or 0) if row else 0.0

        has_required_hours = str(hours_mode or "").lower() == "specified" and float(required_hours or 0) > 0
        if not has_required_hours:
            return {
                "hours_mode": "not_specified",
                "required_hours": None,
                "rendered_hours": round(rendered_hours, 2),
                "remaining_hours": None,
                "progress_percent": None,
                "is_complete": False,
            }

        required_hours = float(required_hours)
        remaining_hours = max(required_hours - rendered_hours, 0.0)
        progress_percent = min((rendered_hours / required_hours) * 100.0, 100.0)

        return {
            "hours_mode": "specified",
            "required_hours": round(required_hours, 2),
            "rendered_hours": round(rendered_hours, 2),
            "remaining_hours": round(remaining_hours, 2),
            "progress_percent": round(progress_percent, 1),
            "is_complete": rendered_hours >= required_hours,
        }
    finally:
        conn.close()
