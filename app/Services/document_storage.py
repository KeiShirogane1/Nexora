"""Database-backed persistence helpers for student documents.

Student documents keep their existing database row and local filepath for
backward compatibility. The actual file bytes are also stored in the documents
table so Render/PostgreSQL is the durable source and the filesystem is only a
cache.
"""

import os
from pathlib import Path

from app.Models.db import get_db_connection, using_postgres


MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
_schema_ready = False


class DocumentStorageError(RuntimeError):
    """Raised when database-backed document storage cannot complete safely."""


def normalize_document_bytes(value):
    """Normalize SQLite/Postgres binary values to bytes while preserving NULL."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    try:
        return bytes(value)
    except (TypeError, ValueError):
        return None


def ensure_document_storage_schema():
    """Ensure documents.file_data exists on both PostgreSQL and SQLite."""
    global _schema_ready
    if _schema_ready:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if using_postgres():
            cursor.execute(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_data BYTEA"
            )
        else:
            columns = {
                row[1]
                for row in cursor.execute("PRAGMA table_info(documents)").fetchall()
            }
            if "file_data" not in columns:
                cursor.execute("ALTER TABLE documents ADD COLUMN file_data BLOB")
        conn.commit()
        _schema_ready = True
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        raise DocumentStorageError(
            "Unable to initialize database-backed document storage."
        ) from exc
    finally:
        cursor.close()
        conn.close()


def store_document_bytes(document_id, student_id, data):
    """Persist one validated student document's bytes in the documents row."""
    ensure_document_storage_schema()
    payload = normalize_document_bytes(data)
    if payload is None:
        raise DocumentStorageError("Document bytes are unavailable.")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise DocumentStorageError("Document exceeds the supported 5 MB limit.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE documents
            SET file_data = ?
            WHERE id = ? AND student_id = ?
            """,
            (payload, int(document_id), int(student_id)),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        raise DocumentStorageError(
            "Unable to persist document bytes in the database."
        ) from exc
    finally:
        cursor.close()
        conn.close()


def get_document_bytes(document_id, student_id=None):
    """Read a document BLOB/BYTEA from the database without exposing its path."""
    ensure_document_storage_schema()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if student_id is None:
            cursor.execute(
                "SELECT file_data FROM documents WHERE id = ? LIMIT 1",
                (int(document_id),),
            )
        else:
            cursor.execute(
                """
                SELECT file_data
                FROM documents
                WHERE id = ? AND student_id = ?
                LIMIT 1
                """,
                (int(document_id), int(student_id)),
            )
        row = cursor.fetchone()
        if not row:
            return None
        return normalize_document_bytes(row[0])
    finally:
        cursor.close()
        conn.close()


def current_document_path(upload_folder, filepath, filename):
    """Return the safe current cache path for a legacy document filename."""
    if not upload_folder:
        return None

    stored_name = str(filepath or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not stored_name:
        stored_name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    stored_name = stored_name.strip()
    if not stored_name or stored_name in {".", ".."}:
        return None

    try:
        base = Path(upload_folder).resolve()
        candidate = (base / stored_name).resolve()
        if candidate.parent != base:
            return None
        return str(candidate)
    except (OSError, RuntimeError, ValueError):
        return None


def restore_document_local(document_id, student_id, filename, filepath, upload_folder):
    """Restore a DB-backed document to the current local upload cache if needed."""
    data = get_document_bytes(document_id, student_id)
    if data is None or len(data) > MAX_DOCUMENT_BYTES:
        return None

    target = current_document_path(upload_folder, filepath, filename)
    if not target:
        return None

    target_path = Path(target)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if not target_path.is_file():
            temporary = target_path.with_name(f".{target_path.name}.db.tmp")
            temporary.write_bytes(data)
            temporary.replace(target_path)
    except OSError:
        return None

    try:
        current_path = os.path.realpath(filepath) if filepath else ""
        restored_path = os.path.realpath(target)
    except (OSError, ValueError, TypeError):
        current_path = str(filepath or "")
        restored_path = str(target)

    if current_path != restored_path:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE documents
                SET filepath = ?
                WHERE id = ? AND student_id = ?
                """,
                (target, int(document_id), int(student_id)),
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    return target
