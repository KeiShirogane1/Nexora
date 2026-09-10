"""Attendance schema helpers for Intern Classroom-scoped OJT sessions."""
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
