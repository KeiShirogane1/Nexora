"""Supervisor review workflow for structured Daily OJT Logbook entries."""
from datetime import datetime
from pathlib import Path

from app.Models.db import get_db_connection, using_postgres
from app.Services.logbook_photo_service import PHOTO_ROOT


REVIEW_STATUSES = {"pending", "reviewed", "approved", "revision_requested"}
MAX_REVIEW_COMMENT_LENGTH = 3000
MAX_LOG_TEXT_LENGTH = 5000


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


def review_status_label(status):
    return {
        "in_progress": "In Progress",
        "pending": "Pending Review",
        "reviewed": "Reviewed",
        "approved": "Approved",
        "revision_requested": "Revision Requested",
    }.get(status, "Pending Review")


def ensure_logbook_review_schema():
    """Create the additive 1:1 supervisor review table for Daily OJT entries."""
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logbook_reviews (
                    log_id INTEGER PRIMARY KEY REFERENCES logs(id) ON DELETE CASCADE,
                    supervisor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    comments TEXT,
                    reviewed_at TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logbook_reviews (
                    log_id INTEGER PRIMARY KEY REFERENCES logs(id) ON DELETE CASCADE,
                    supervisor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    comments TEXT,
                    reviewed_at TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_logbook_reviews_supervisor_status ON logbook_reviews(supervisor_id, status)"
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


def _owned_classroom(conn, supervisor_id, classroom_id):
    return conn.execute(
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


def _day_map(conn, classroom_id):
    rows = conn.execute(
        """
        SELECT id, student_id
        FROM attendance
        WHERE classroom_id = ?
        ORDER BY student_id ASC, clock_in ASC, id ASC
        """,
        (classroom_id,),
    ).fetchall()
    counts = {}
    mapping = {}
    for row in rows:
        attendance_id = int(_row_value(row, "id", 0, 0))
        student_id = int(_row_value(row, "student_id", 1, 0))
        counts[student_id] = counts.get(student_id, 0) + 1
        mapping[attendance_id] = counts[student_id]
    return mapping


def _serialize_entry(row, day_map):
    attendance_id = int(_row_value(row, "attendance_id", 1, 0))
    student_id = int(_row_value(row, "student_id", 2, 0))
    hours = _row_value(row, "hours_rendered", 13, None)
    try:
        hours = float(hours) if hours is not None else None
    except (TypeError, ValueError):
        hours = None
    first_name = (_row_value(row, "first_name", 17, "") or "").strip()
    last_name = (_row_value(row, "last_name", 18, "") or "").strip()
    username = (_row_value(row, "username", 15, "") or "").strip()
    email = (_row_value(row, "email", 16, "") or "").strip()
    display_name = " ".join(part for part in (first_name, last_name) if part).strip() or username or email or "Intern"
    attendance_status = _row_value(row, "attendance_status", 14, "Open")
    review_status = "in_progress" if attendance_status == "Open" else (_row_value(row, "review_status", 19, "pending") or "pending")
    return {
        "id": int(_row_value(row, "id", 0, 0)),
        "attendance_id": attendance_id,
        "student_id": student_id,
        "student_name": display_name,
        "student_email": email,
        "day_number": day_map.get(attendance_id),
        "accomplishment": _row_value(row, "accomplishment", 3, "") or "",
        "reflection": _row_value(row, "reflection", 4, "") or "",
        "challenges": _row_value(row, "challenges", 5, "") or "",
        "related_assignment_id": _row_value(row, "related_assignment_id", 6, None),
        "related_work_title": _row_value(row, "related_work_title", 7, None),
        "created_at": _row_value(row, "created_at", 8, None),
        "updated_at": _row_value(row, "updated_at", 9, None),
        "date": _format_date(_row_value(row, "clock_in", 10, None)),
        "time_in": _format_time(_row_value(row, "clock_in", 10, None)),
        "time_out": _format_time(_row_value(row, "clock_out", 11, None)),
        "hours_rendered": hours,
        "attendance_status": attendance_status,
        "review_status": review_status,
        "review_status_label": review_status_label(review_status),
        "review_comments": _row_value(row, "review_comments", 20, "") or "",
        "reviewed_at": _row_value(row, "reviewed_at", 21, None),
        "review_updated_at": _row_value(row, "review_updated_at", 22, None),
        "photo_count": int(_row_value(row, "photo_count", 23, 0) or 0),
        "can_review": attendance_status != "Open",
    }


def get_supervisor_logbook_context(supervisor_id, classroom_id, selected_log_id=None):
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
        selected_log_id = int(selected_log_id) if selected_log_id is not None else None
    except (TypeError, ValueError):
        return {"ok": False, "status_code": 404}

    conn = get_db_connection()
    try:
        classroom_row = _owned_classroom(conn, supervisor_id, classroom_id)
        if not classroom_row:
            exists = conn.execute("SELECT 1 FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
            return {"ok": False, "status_code": 403 if exists else 404}

        day_map = _day_map(conn, classroom_id)
        rows = conn.execute(
            """
            SELECT
                l.id,
                l.attendance_id,
                l.student_id,
                l.accomplishment,
                l.reflection,
                l.challenges,
                l.related_assignment_id,
                ca.title AS related_work_title,
                l.created_at,
                l.updated_at,
                a.clock_in,
                a.clock_out,
                a.classroom_id,
                a.hours_rendered,
                a.status AS attendance_status,
                u.username,
                u.email,
                COALESCE(sp.first_name, '') AS first_name,
                COALESCE(sp.last_name, '') AS last_name,
                COALESCE(r.status, 'pending') AS review_status,
                COALESCE(r.comments, '') AS review_comments,
                r.reviewed_at,
                r.updated_at AS review_updated_at,
                (SELECT COUNT(*) FROM logbook_photos p WHERE p.log_id = l.id) AS photo_count
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            JOIN users u ON u.id = l.student_id
            LEFT JOIN student_profiles sp ON sp.user_id = l.student_id
            LEFT JOIN classroom_assignments ca ON ca.id = l.related_assignment_id
            LEFT JOIN logbook_reviews r ON r.log_id = l.id
            WHERE l.entry_type = 'daily'
              AND a.classroom_id = ?
            ORDER BY a.clock_in DESC, l.id DESC
            """,
            (classroom_id,),
        ).fetchall()
        entries = [_serialize_entry(row, day_map) for row in rows]
        selected_entry = None
        if selected_log_id is not None:
            selected_entry = next((entry for entry in entries if entry["id"] == selected_log_id), None)
            if selected_entry is None:
                return {"ok": False, "status_code": 404}
        elif entries:
            selected_entry = entries[0]

        photos = []
        if selected_entry:
            photo_rows = conn.execute(
                """
                SELECT id, original_filename, mime_type, size_bytes, uploaded_at
                FROM logbook_photos
                WHERE log_id = ?
                ORDER BY uploaded_at ASC, id ASC
                """,
                (selected_entry["id"],),
            ).fetchall()
            photos = [
                {
                    "id": int(_row_value(row, "id", 0, 0)),
                    "original_filename": _row_value(row, "original_filename", 1, "Photo"),
                    "mime_type": _row_value(row, "mime_type", 2, "image/jpeg"),
                    "size_bytes": int(_row_value(row, "size_bytes", 3, 0) or 0),
                    "uploaded_at": _row_value(row, "uploaded_at", 4, None),
                }
                for row in photo_rows
            ]

        summary = {"total": len(entries), "pending": 0, "reviewed": 0, "approved": 0, "revision_requested": 0, "in_progress": 0}
        for entry in entries:
            status = entry["review_status"]
            if status in summary:
                summary[status] += 1

        return {
            "ok": True,
            "status_code": 200,
            "classroom": _classroom_dict(classroom_row),
            "entries": entries,
            "selected_entry": selected_entry,
            "selected_photos": photos,
            "summary": summary,
        }
    finally:
        conn.close()


def save_supervisor_review(supervisor_id, classroom_id, log_id, status, comments=""):
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
        log_id = int(log_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid Daily OJT entry."}

    status = (status or "").strip().lower()
    comments = (comments or "").strip()
    if status not in {"reviewed", "approved", "revision_requested"}:
        return {"ok": False, "error": "Choose a valid review action."}
    if len(comments) > MAX_REVIEW_COMMENT_LENGTH:
        return {"ok": False, "error": f"Supervisor comments must be {MAX_REVIEW_COMMENT_LENGTH:,} characters or fewer."}
    if status == "revision_requested" and not comments:
        return {"ok": False, "error": "Add a supervisor comment explaining what the intern should revise."}

    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT l.student_id, l.attendance_id, a.status AS attendance_status
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            JOIN classrooms c ON c.id = a.classroom_id
            WHERE l.id = ?
              AND l.entry_type = 'daily'
              AND a.classroom_id = ?
              AND c.supervisor_id = ?
            LIMIT 1
            """,
            (log_id, classroom_id, supervisor_id),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "Daily OJT entry not found."}
        if _row_value(row, "attendance_status", 2, "Open") == "Open":
            return {"ok": False, "error": "Clock-out must be completed before this Daily OJT entry can be reviewed."}

        now = datetime.now()
        conn.execute(
            """
            INSERT INTO logbook_reviews (log_id, supervisor_id, status, comments, reviewed_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (log_id) DO UPDATE SET
                supervisor_id = excluded.supervisor_id,
                status = excluded.status,
                comments = excluded.comments,
                reviewed_at = excluded.reviewed_at,
                updated_at = excluded.updated_at
            """,
            (log_id, supervisor_id, status, comments or None, now, now),
        )
        conn.commit()
        return {
            "ok": True,
            "error": None,
            "student_id": int(_row_value(row, "student_id", 0, 0)),
            "attendance_id": int(_row_value(row, "attendance_id", 1, 0)),
            "classroom_id": classroom_id,
            "log_id": log_id,
            "status": status,
            "status_label": review_status_label(status),
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def get_student_review_page(student_id, log_id):
    try:
        student_id = int(student_id)
        log_id = int(log_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT
                l.id, l.attendance_id, l.accomplishment, l.reflection, l.challenges,
                ca.title AS related_work_title,
                a.classroom_id, a.clock_in, a.clock_out, a.hours_rendered, a.status AS attendance_status,
                c.name AS classroom_name, c.section, COALESCE(cid.company_name, '') AS company_name,
                COALESCE(r.status, 'pending') AS review_status,
                COALESCE(r.comments, '') AS review_comments,
                r.reviewed_at,
                r.updated_at AS review_updated_at,
                c.supervisor_id
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            JOIN classrooms c ON c.id = a.classroom_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            LEFT JOIN classroom_assignments ca ON ca.id = l.related_assignment_id
            LEFT JOIN logbook_reviews r ON r.log_id = l.id
            WHERE l.id = ?
              AND l.student_id = ?
              AND a.student_id = ?
              AND l.entry_type = 'daily'
            LIMIT 1
            """,
            (log_id, student_id, student_id),
        ).fetchone()
        if not row:
            return None

        classroom_id = int(_row_value(row, "classroom_id", 6, 0))
        day_map = _day_map(conn, classroom_id)
        attendance_id = int(_row_value(row, "attendance_id", 1, 0))
        attendance_status = _row_value(row, "attendance_status", 10, "Open")
        stored_review_status = _row_value(row, "review_status", 14, "pending") or "pending"
        review_status = "in_progress" if attendance_status == "Open" else stored_review_status
        hours = _row_value(row, "hours_rendered", 9, None)
        try:
            hours = float(hours) if hours is not None else None
        except (TypeError, ValueError):
            hours = None
        return {
            "id": log_id,
            "attendance_id": attendance_id,
            "classroom_id": classroom_id,
            "classroom_name": _row_value(row, "classroom_name", 11, "Intern Classroom"),
            "section": _row_value(row, "section", 12, ""),
            "company_name": _row_value(row, "company_name", 13, ""),
            "supervisor_id": int(_row_value(row, "supervisor_id", 18, 0)),
            "day_number": day_map.get(attendance_id),
            "date": _format_date(_row_value(row, "clock_in", 7, None)),
            "time_in": _format_time(_row_value(row, "clock_in", 7, None)),
            "time_out": _format_time(_row_value(row, "clock_out", 8, None)),
            "hours_rendered": hours,
            "attendance_status": attendance_status,
            "accomplishment": _row_value(row, "accomplishment", 2, "") or "",
            "reflection": _row_value(row, "reflection", 3, "") or "",
            "challenges": _row_value(row, "challenges", 4, "") or "",
            "related_work_title": _row_value(row, "related_work_title", 5, None),
            "review_status": review_status,
            "review_status_label": review_status_label(review_status),
            "review_comments": _row_value(row, "review_comments", 15, "") or "",
            "reviewed_at": _row_value(row, "reviewed_at", 16, None),
            "review_updated_at": _row_value(row, "review_updated_at", 17, None),
            "can_revise": stored_review_status == "revision_requested",
        }
    finally:
        conn.close()


def revise_daily_log(student_id, log_id, accomplishment, reflection="", challenges=""):
    try:
        student_id = int(student_id)
        log_id = int(log_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid Daily OJT entry."}

    accomplishment = (accomplishment or "").strip()
    reflection = (reflection or "").strip()
    challenges = (challenges or "").strip()
    if not accomplishment:
        return {"ok": False, "error": "Daily accomplishment is required."}
    if any(len(value) > MAX_LOG_TEXT_LENGTH for value in (accomplishment, reflection, challenges)):
        return {"ok": False, "error": f"Each Daily OJT text field must be {MAX_LOG_TEXT_LENGTH:,} characters or fewer."}

    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT l.attendance_id, a.classroom_id, c.supervisor_id, r.status
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            JOIN classrooms c ON c.id = a.classroom_id
            JOIN logbook_reviews r ON r.log_id = l.id
            WHERE l.id = ?
              AND l.student_id = ?
              AND a.student_id = ?
              AND l.entry_type = 'daily'
              AND r.status = 'revision_requested'
            LIMIT 1
            """,
            (log_id, student_id, student_id),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "This Daily OJT entry is not currently open for revision."}

        now = datetime.now()
        conn.execute(
            """
            UPDATE logs
            SET content = ?, accomplishment = ?, reflection = ?, challenges = ?, updated_at = ?
            WHERE id = ? AND student_id = ?
            """,
            (accomplishment, accomplishment, reflection or None, challenges or None, now, log_id, student_id),
        )
        conn.execute(
            """
            UPDATE logbook_reviews
            SET status = 'pending', updated_at = ?
            WHERE log_id = ?
            """,
            (now, log_id),
        )
        conn.commit()
        return {
            "ok": True,
            "error": None,
            "log_id": log_id,
            "attendance_id": int(_row_value(row, "attendance_id", 0, 0)),
            "classroom_id": int(_row_value(row, "classroom_id", 1, 0)),
            "supervisor_id": int(_row_value(row, "supervisor_id", 2, 0)),
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _safe_photo_path(relative_path):
    root = PHOTO_ROOT.resolve()
    candidate = (root / str(relative_path)).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


def get_supervisor_logbook_photo(supervisor_id, classroom_id, photo_id):
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
        photo_id = int(photo_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT p.relative_path, p.original_filename, p.mime_type
            FROM logbook_photos p
            JOIN logs l ON l.id = p.log_id
            JOIN attendance a ON a.id = l.attendance_id
            JOIN classrooms c ON c.id = a.classroom_id
            WHERE p.id = ?
              AND l.entry_type = 'daily'
              AND a.classroom_id = ?
              AND c.supervisor_id = ?
            LIMIT 1
            """,
            (photo_id, classroom_id, supervisor_id),
        ).fetchone()
        if not row:
            return None
        path = _safe_photo_path(_row_value(row, "relative_path", 0, ""))
        if path is None or not path.is_file():
            return None
        return {
            "path": path,
            "original_filename": _row_value(row, "original_filename", 1, "photo"),
            "mime_type": _row_value(row, "mime_type", 2, "image/jpeg"),
        }
    finally:
        conn.close()
