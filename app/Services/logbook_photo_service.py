"""Private photo evidence storage for structured Daily OJT Logbook entries."""
from datetime import datetime
from pathlib import Path
import secrets

from werkzeug.utils import secure_filename

from app.Models.db import get_db_connection, using_postgres


MAX_PHOTOS_PER_LOG = 5
MAX_PHOTO_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
PHOTO_ROOT = Path(__file__).resolve().parents[2] / "storage" / "logbook_photos"


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


def ensure_logbook_photo_schema():
    """Create the additive private photo-evidence table for Daily OJT logs."""
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logbook_photos (
                    id SERIAL PRIMARY KEY,
                    log_id INTEGER NOT NULL REFERENCES logs(id) ON DELETE CASCADE,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logbook_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_id INTEGER NOT NULL REFERENCES logs(id) ON DELETE CASCADE,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_logbook_photos_log_id ON logbook_photos(log_id)"
        )
        conn.commit()
        PHOTO_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _owned_daily_log(conn, student_id, log_id, require_open=False):
    sql = """
        SELECT l.id, l.attendance_id, a.classroom_id, a.status
        FROM logs l
        JOIN attendance a ON a.id = l.attendance_id
        WHERE l.id = ?
          AND l.student_id = ?
          AND a.student_id = ?
          AND l.entry_type = 'daily'
    """
    params = [log_id, student_id, student_id]
    if require_open:
        sql += " AND a.status = 'Open'"
    sql += " LIMIT 1"
    return conn.execute(sql, tuple(params)).fetchone()


def _daily_log_for_attendance(conn, student_id, attendance_id, require_open=False):
    sql = """
        SELECT l.id, l.attendance_id, a.classroom_id, a.status
        FROM logs l
        JOIN attendance a ON a.id = l.attendance_id
        WHERE l.attendance_id = ?
          AND l.student_id = ?
          AND a.student_id = ?
          AND l.entry_type = 'daily'
    """
    params = [attendance_id, student_id, student_id]
    if require_open:
        sql += " AND a.status = 'Open'"
    sql += " LIMIT 1"
    return conn.execute(sql, tuple(params)).fetchone()


def _image_kind(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg", "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None, None


def _validated_photo(file_storage):
    original = secure_filename(file_storage.filename or "")
    if not original or "." not in original:
        return None, "Choose a JPG, PNG, or WebP image."

    extension = original.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return None, f"Unsupported photo type: {original}"

    data = file_storage.read(MAX_PHOTO_BYTES + 1)
    try:
        file_storage.seek(0)
    except Exception:
        pass

    if not data:
        return None, f"Photo is empty: {original}"
    if len(data) > MAX_PHOTO_BYTES:
        return None, f"Photo exceeds the 8 MB limit: {original}"

    detected_kind, mime_type = _image_kind(data)
    extension_kind = "jpeg" if extension in {"jpg", "jpeg"} else extension
    if detected_kind != extension_kind:
        return None, f"Photo content does not match its file type: {original}"

    suffix = ".jpg" if detected_kind == "jpeg" else f".{detected_kind}"
    return {
        "original_filename": original,
        "data": data,
        "mime_type": mime_type,
        "suffix": suffix,
        "size_bytes": len(data),
    }, None


def _safe_photo_path(relative_path):
    root = PHOTO_ROOT.resolve()
    candidate = (root / str(relative_path)).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


def _save_photos_for_log(student_id, log_row, files):
    uploaded = [item for item in (files or []) if item and getattr(item, "filename", "")]
    if not uploaded:
        return {
            "ok": True,
            "added": 0,
            "error": None,
            "log_id": int(_row_value(log_row, "id", 0, 0)),
            "attendance_id": int(_row_value(log_row, "attendance_id", 1, 0)),
            "classroom_id": _row_value(log_row, "classroom_id", 2, None),
        }

    log_id = int(_row_value(log_row, "id", 0, 0))
    attendance_id = int(_row_value(log_row, "attendance_id", 1, 0))
    classroom_id = _row_value(log_row, "classroom_id", 2, None)

    conn = get_db_connection()
    written_paths = []
    try:
        owned = _owned_daily_log(conn, student_id, log_id, require_open=True)
        if not owned:
            return {
                "ok": False,
                "added": 0,
                "error": "Photo evidence can only be changed while the attendance session is open.",
                "log_id": log_id,
                "attendance_id": attendance_id,
                "classroom_id": classroom_id,
            }

        count_row = conn.execute(
            "SELECT COUNT(*) FROM logbook_photos WHERE log_id = ?",
            (log_id,),
        ).fetchone()
        existing_count = int(count_row[0] if count_row else 0)
        if existing_count + len(uploaded) > MAX_PHOTOS_PER_LOG:
            return {
                "ok": False,
                "added": 0,
                "error": f"A Daily OJT entry can contain up to {MAX_PHOTOS_PER_LOG} photos.",
                "log_id": log_id,
                "attendance_id": attendance_id,
                "classroom_id": classroom_id,
            }

        validated = []
        for item in uploaded:
            photo, error = _validated_photo(item)
            if error:
                return {
                    "ok": False,
                    "added": 0,
                    "error": error,
                    "log_id": log_id,
                    "attendance_id": attendance_id,
                    "classroom_id": classroom_id,
                }
            validated.append(photo)

        folder = PHOTO_ROOT / str(int(student_id)) / str(log_id)
        folder.mkdir(parents=True, exist_ok=True)
        now = datetime.now()

        for photo in validated:
            stored_filename = f"{secrets.token_hex(16)}{photo['suffix']}"
            relative_path = Path(str(int(student_id))) / str(log_id) / stored_filename
            destination = _safe_photo_path(relative_path)
            if destination is None:
                raise RuntimeError("Invalid logbook photo storage path.")

            destination.write_bytes(photo["data"])
            written_paths.append(destination)
            conn.execute(
                """
                INSERT INTO logbook_photos (
                    log_id,
                    original_filename,
                    stored_filename,
                    relative_path,
                    mime_type,
                    size_bytes,
                    uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    photo["original_filename"],
                    stored_filename,
                    str(relative_path),
                    photo["mime_type"],
                    photo["size_bytes"],
                    now,
                ),
            )

        conn.commit()
        return {
            "ok": True,
            "added": len(validated),
            "error": None,
            "log_id": log_id,
            "attendance_id": attendance_id,
            "classroom_id": classroom_id,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        for path in written_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        raise
    finally:
        conn.close()


def add_photos_for_attendance(student_id, attendance_id, files):
    try:
        student_id = int(student_id)
        attendance_id = int(attendance_id)
    except (TypeError, ValueError):
        return {"ok": False, "added": 0, "error": "Invalid attendance session."}

    conn = get_db_connection()
    try:
        log_row = _daily_log_for_attendance(conn, student_id, attendance_id, require_open=True)
    finally:
        conn.close()

    if not log_row:
        return {
            "ok": False,
            "added": 0,
            "error": "Save the Daily OJT entry before attaching photo evidence.",
            "attendance_id": attendance_id,
        }
    return _save_photos_for_log(student_id, log_row, files)


def add_logbook_photos(student_id, log_id, files):
    try:
        student_id = int(student_id)
        log_id = int(log_id)
    except (TypeError, ValueError):
        return {"ok": False, "added": 0, "error": "Invalid Daily OJT entry."}

    conn = get_db_connection()
    try:
        log_row = _owned_daily_log(conn, student_id, log_id, require_open=True)
    finally:
        conn.close()

    if not log_row:
        return {
            "ok": False,
            "added": 0,
            "error": "Photo evidence can only be changed while the attendance session is open.",
            "log_id": log_id,
        }
    return _save_photos_for_log(student_id, log_row, files)


def get_logbook_photos(student_id, log_id):
    try:
        student_id = int(student_id)
        log_id = int(log_id)
    except (TypeError, ValueError):
        return []

    conn = get_db_connection()
    try:
        if not _owned_daily_log(conn, student_id, log_id):
            return []
        rows = conn.execute(
            """
            SELECT id, original_filename, mime_type, size_bytes, uploaded_at
            FROM logbook_photos
            WHERE log_id = ?
            ORDER BY uploaded_at ASC, id ASC
            """,
            (log_id,),
        ).fetchall()
        return [
            {
                "id": int(_row_value(row, "id", 0, 0)),
                "original_filename": _row_value(row, "original_filename", 1, "Photo"),
                "mime_type": _row_value(row, "mime_type", 2, "image/jpeg"),
                "size_bytes": int(_row_value(row, "size_bytes", 3, 0) or 0),
                "uploaded_at": _row_value(row, "uploaded_at", 4, None),
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_photo_for_student(student_id, photo_id):
    try:
        student_id = int(student_id)
        photo_id = int(photo_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT p.id, p.relative_path, p.original_filename, p.mime_type
            FROM logbook_photos p
            JOIN logs l ON l.id = p.log_id
            JOIN attendance a ON a.id = l.attendance_id
            WHERE p.id = ?
              AND l.student_id = ?
              AND a.student_id = ?
              AND l.entry_type = 'daily'
            LIMIT 1
            """,
            (photo_id, student_id, student_id),
        ).fetchone()
        if not row:
            return None

        path = _safe_photo_path(_row_value(row, "relative_path", 1, ""))
        if path is None or not path.is_file():
            return None
        return {
            "id": int(_row_value(row, "id", 0, 0)),
            "path": path,
            "original_filename": _row_value(row, "original_filename", 2, "photo"),
            "mime_type": _row_value(row, "mime_type", 3, "image/jpeg"),
        }
    finally:
        conn.close()


def delete_logbook_photo(student_id, photo_id):
    try:
        student_id = int(student_id)
        photo_id = int(photo_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid photo evidence."}

    conn = get_db_connection()
    path = None
    try:
        row = conn.execute(
            """
            SELECT p.id, p.relative_path, l.id AS log_id, l.attendance_id, a.classroom_id
            FROM logbook_photos p
            JOIN logs l ON l.id = p.log_id
            JOIN attendance a ON a.id = l.attendance_id
            WHERE p.id = ?
              AND l.student_id = ?
              AND a.student_id = ?
              AND l.entry_type = 'daily'
              AND a.status = 'Open'
            LIMIT 1
            """,
            (photo_id, student_id, student_id),
        ).fetchone()
        if not row:
            return {
                "ok": False,
                "error": "Photo evidence can only be removed from your open Daily OJT entry.",
            }

        path = _safe_photo_path(_row_value(row, "relative_path", 1, ""))
        log_id = int(_row_value(row, "log_id", 2, 0))
        attendance_id = int(_row_value(row, "attendance_id", 3, 0))
        classroom_id = _row_value(row, "classroom_id", 4, None)
        conn.execute("DELETE FROM logbook_photos WHERE id = ?", (photo_id,))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    return {
        "ok": True,
        "error": None,
        "log_id": log_id,
        "attendance_id": attendance_id,
        "classroom_id": classroom_id,
    }
