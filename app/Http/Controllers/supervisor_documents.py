import os
from datetime import datetime
from io import BytesIO

from flask import Blueprint, abort, current_app, g, render_template, request, send_file, session
from werkzeug.utils import secure_filename

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.document_storage import (
    MAX_DOCUMENT_BYTES,
    DocumentStorageError,
    current_document_path,
    ensure_document_storage_schema,
    normalize_document_bytes,
    restore_document_local,
    store_document_bytes,
)


supervisor_documents = Blueprint("supervisor_documents", __name__)


def _value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except (AttributeError, KeyError, TypeError):
        pass
    try:
        value = row[index]
        return default if value is None else value
    except (IndexError, KeyError, TypeError):
        return default


def _display_name(first_name, middle_name, last_name, username):
    parts = [part for part in (first_name, middle_name, last_name) if part]
    return " ".join(parts) if parts else (username or "Student")


def _format_datetime(value):
    if not value:
        return "—"
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return str(value)
    return parsed.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")


def _format_file_size(size):
    if size is None:
        return "—"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _document_display_name(filename, student_id):
    filename = filename or "Document"
    prefix = f"{student_id}_"
    return filename[len(prefix):] if filename.startswith(prefix) else filename


def _is_safe_upload_path(filepath):
    upload_base = current_app.config.get("UPLOAD_FOLDER", "")
    if not upload_base or not filepath:
        return False
    try:
        base = os.path.realpath(upload_base)
        candidate = os.path.realpath(filepath)
        return os.path.commonpath([base, candidate]) == base
    except (OSError, ValueError, TypeError):
        return False


def _resolve_upload_path(filepath, filename=None):
    upload_base = current_app.config.get("UPLOAD_FOLDER", "")
    if not upload_base:
        return None

    try:
        base = os.path.realpath(upload_base)
    except (OSError, ValueError, TypeError):
        return None

    candidates = []
    if filepath:
        candidates.append(filepath)
        stored_name = str(filepath).replace("\\", "/").rsplit("/", 1)[-1]
        if stored_name:
            candidates.append(os.path.join(base, stored_name))

    if filename:
        stored_name = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
        if stored_name:
            candidates.append(os.path.join(base, stored_name))

    for candidate in candidates:
        try:
            resolved = os.path.realpath(candidate)
            if os.path.commonpath([base, resolved]) == base and os.path.isfile(resolved):
                return resolved
        except (OSError, ValueError, TypeError):
            continue

    return None


def _normalize_delete_filepath(document_id, student_id, filename, filepath):
    target = current_document_path(
        current_app.config.get("UPLOAD_FOLDER", ""),
        filepath,
        filename,
    )
    if not target:
        return

    try:
        old_path = os.path.realpath(filepath) if filepath else ""
        new_path = os.path.realpath(target)
    except (OSError, ValueError, TypeError):
        old_path = str(filepath or "")
        new_path = str(target)

    if old_path == new_path:
        return

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE documents SET filepath = ? WHERE id = ? AND student_id = ?",
            (target, int(document_id), int(student_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _supervisor_owns_student(conn, supervisor_id, student_id):
    return conn.execute(
        """
        SELECT 1
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        WHERE cs.student_id = ? AND c.supervisor_id = ?
        LIMIT 1
        """,
        (student_id, supervisor_id),
    ).fetchone() is not None


@supervisor_documents.before_app_request
def _prepare_student_document_storage():
    endpoint = request.endpoint or ""
    relevant = endpoint.startswith("supervisor_documents.") or endpoint in {
        "student.documents",
        "student.view_document",
        "student.delete_document",
    }
    if not relevant:
        return None

    try:
        ensure_document_storage_schema()
    except DocumentStorageError:
        current_app.logger.exception("Unable to initialize student document database storage")
        raise

    if endpoint == "student.documents" and request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return None

        try:
            data = uploaded.read(MAX_DOCUMENT_BYTES + 1)
            uploaded.seek(0)
        except (OSError, ValueError):
            return None

        safe_name = secure_filename(uploaded.filename)
        if safe_name and len(data) <= MAX_DOCUMENT_BYTES:
            g.nexora_document_upload = (safe_name, data)
        return None

    if endpoint not in {"student.view_document", "student.delete_document"}:
        return None

    document_id = (request.view_args or {}).get("document_id")
    student_id = session.get("user_id")
    if not document_id or not student_id or session.get("role") != "student":
        return None

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT filename, filepath FROM documents WHERE id = ? AND student_id = ? LIMIT 1",
            (document_id, student_id),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    filename = _value(row, "filename", 0, "") or "Document"
    filepath = _value(row, "filepath", 1, "") or ""
    restored = restore_document_local(
        int(document_id),
        int(student_id),
        filename,
        filepath,
        current_app.config.get("UPLOAD_FOLDER", ""),
    )

    if endpoint == "student.delete_document" and not restored:
        # A legacy missing file should still be removable by its owning student.
        _normalize_delete_filepath(document_id, student_id, filename, filepath)
    return None


@supervisor_documents.after_app_request
def _persist_student_document_upload(response):
    if (
        request.endpoint != "student.documents"
        or request.method != "POST"
        or response.status_code >= 400
    ):
        return response

    upload_info = getattr(g, "nexora_document_upload", None)
    user_id = session.get("user_id")
    if not upload_info or not user_id:
        return response

    safe_name, data = upload_info
    expected_filename = f"{user_id}_{safe_name}"
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM documents
            WHERE student_id = ? AND filename = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, expected_filename),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return response

    document_id = int(_value(row, "id", 0, 0) or 0)
    if not document_id:
        return response

    try:
        store_document_bytes(document_id, int(user_id), data)
    except DocumentStorageError:
        current_app.logger.exception(
            "Unable to persist student document %s in the database",
            document_id,
        )
    return response


@supervisor_documents.route("/supervisor/student-documents")
@role_required("supervisor")
def student_documents():
    supervisor_id = int(session["user_id"])
    search = (request.args.get("search") or "").strip().lower()
    classroom_type = (request.args.get("type") or "all").strip().lower()
    document_state = (request.args.get("documents") or "all").strip().lower()

    if classroom_type not in {"all", "classroom", "internship"}:
        classroom_type = "all"
    if document_state not in {"all", "with", "without"}:
        document_state = "all"

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                c.id AS classroom_id,
                c.name AS classroom_name,
                c.section,
                COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                COALESCE(c.archived, 0) AS archived,
                COALESCE(cid.company_name, '') AS company_name,
                u.id AS student_id,
                u.username,
                u.email,
                COALESCE(sp.first_name, '') AS first_name,
                COALESCE(sp.middle_name, '') AS middle_name,
                COALESCE(sp.last_name, '') AS last_name,
                COALESCE(sp.student_id, '') AS student_number,
                COALESCE(sp.major_program, '') AS major_program,
                COALESCE(sp.grade_year, '') AS grade_year,
                (SELECT COUNT(*) FROM documents d WHERE d.student_id = u.id) AS document_count,
                (SELECT MAX(d.uploaded_at) FROM documents d WHERE d.student_id = u.id) AS last_upload
            FROM classrooms c
            JOIN classroom_students cs ON cs.classroom_id = c.id
            JOIN users u ON u.id = cs.student_id
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.supervisor_id = ? AND u.role = 'student'
            ORDER BY COALESCE(c.archived, 0), LOWER(c.name), c.id, LOWER(u.username), u.id
            """,
            (supervisor_id,),
        ).fetchall()
        classroom_count = conn.execute(
            "SELECT COUNT(*) FROM classrooms WHERE supervisor_id = ?",
            (supervisor_id,),
        ).fetchone()[0]
        total_documents = conn.execute(
            """
            SELECT COUNT(*)
            FROM documents d
            WHERE EXISTS (
                SELECT 1
                FROM classroom_students cs
                JOIN classrooms c ON c.id = cs.classroom_id
                WHERE cs.student_id = d.student_id AND c.supervisor_id = ?
            )
            """,
            (supervisor_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    grouped = {}
    classroom_order = []
    unique_students = {}

    for row in rows:
        row_type = (_value(row, "classroom_type", 3, "classroom") or "classroom").lower()
        if classroom_type != "all" and row_type != classroom_type:
            continue

        student_id = int(_value(row, "student_id", 6, 0) or 0)
        document_count = int(_value(row, "document_count", 15, 0) or 0)
        if document_state == "with" and document_count <= 0:
            continue
        if document_state == "without" and document_count > 0:
            continue

        username = _value(row, "username", 7, "") or ""
        student = {
            "id": student_id,
            "username": username,
            "email": _value(row, "email", 8, "") or "",
            "display_name": _display_name(
                _value(row, "first_name", 9, "") or "",
                _value(row, "middle_name", 10, "") or "",
                _value(row, "last_name", 11, "") or "",
                username,
            ),
            "student_number": _value(row, "student_number", 12, "") or "",
            "major_program": _value(row, "major_program", 13, "") or "",
            "grade_year": _value(row, "grade_year", 14, "") or "",
            "document_count": document_count,
            "last_upload": _format_datetime(_value(row, "last_upload", 16, None)),
        }

        classroom_search = " ".join(
            [
                _value(row, "classroom_name", 1, "") or "",
                _value(row, "section", 2, "") or "",
                _value(row, "company_name", 5, "") or "",
            ]
        )
        if search:
            haystack = " ".join(
                [
                    student["display_name"],
                    student["username"],
                    student["email"],
                    student["student_number"],
                    student["major_program"],
                    student["grade_year"],
                    classroom_search,
                ]
            ).lower()
            if search not in haystack:
                continue

        classroom_id = int(_value(row, "classroom_id", 0, 0) or 0)
        if classroom_id not in grouped:
            grouped[classroom_id] = {
                "id": classroom_id,
                "name": _value(row, "classroom_name", 1, "") or "Classroom",
                "section": _value(row, "section", 2, "") or "",
                "classroom_type": row_type,
                "archived": bool(int(_value(row, "archived", 4, 0) or 0)),
                "company_name": _value(row, "company_name", 5, "") or "",
                "students": [],
            }
            classroom_order.append(classroom_id)
        grouped[classroom_id]["students"].append(student)
        unique_students[student_id] = student

    classroom_groups = [grouped[classroom_id] for classroom_id in classroom_order]
    with_documents = sum(1 for student in unique_students.values() if student["document_count"] > 0)
    summary = {
        "total_students": len(unique_students),
        "with_documents": with_documents,
        "total_documents": int(total_documents or 0),
        "total_classrooms": int(classroom_count or 0),
    }

    return render_template(
        "supervisor/student_documents.html",
        classroom_groups=classroom_groups,
        summary=summary,
        search=request.args.get("search", ""),
        classroom_type=classroom_type,
        document_state=document_state,
        active_page="student_documents",
    )


@supervisor_documents.route("/supervisor/student-documents/<int:student_id>")
@role_required("supervisor")
def student_document_folder(student_id):
    supervisor_id = int(session["user_id"])
    conn = get_db_connection()
    try:
        if not _supervisor_owns_student(conn, supervisor_id, student_id):
            abort(404)

        student_row = conn.execute(
            """
            SELECT u.id, u.username, u.email,
                   COALESCE(sp.first_name, '') AS first_name,
                   COALESCE(sp.middle_name, '') AS middle_name,
                   COALESCE(sp.last_name, '') AS last_name,
                   COALESCE(sp.student_id, '') AS student_number,
                   COALESCE(sp.major_program, '') AS major_program,
                   COALESCE(sp.grade_year, '') AS grade_year
            FROM users u
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE u.id = ? AND u.role = 'student'
            LIMIT 1
            """,
            (student_id,),
        ).fetchone()
        if not student_row:
            abort(404)

        document_rows = conn.execute(
            """
            SELECT id, filename, filepath, uploaded_at, LENGTH(file_data) AS stored_size
            FROM documents
            WHERE student_id = ?
            ORDER BY uploaded_at DESC, id DESC
            """,
            (student_id,),
        ).fetchall()
        membership_rows = conn.execute(
            """
            SELECT c.id, c.name, c.section,
                   COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                   COALESCE(c.archived, 0) AS archived,
                   COALESCE(cid.company_name, '') AS company_name
            FROM classroom_students cs
            JOIN classrooms c ON c.id = cs.classroom_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE cs.student_id = ? AND c.supervisor_id = ?
            ORDER BY COALESCE(c.archived, 0), LOWER(c.name), c.id
            """,
            (student_id, supervisor_id),
        ).fetchall()
    finally:
        conn.close()

    username = _value(student_row, "username", 1, "") or ""
    student = {
        "id": int(_value(student_row, "id", 0, 0) or 0),
        "username": username,
        "email": _value(student_row, "email", 2, "") or "",
        "display_name": _display_name(
            _value(student_row, "first_name", 3, "") or "",
            _value(student_row, "middle_name", 4, "") or "",
            _value(student_row, "last_name", 5, "") or "",
            username,
        ),
        "student_number": _value(student_row, "student_number", 6, "") or "",
        "major_program": _value(student_row, "major_program", 7, "") or "",
        "grade_year": _value(student_row, "grade_year", 8, "") or "",
    }

    documents = []
    for row in document_rows:
        document_id = int(_value(row, "id", 0, 0) or 0)
        filename = _value(row, "filename", 1, "") or "Document"
        filepath = _value(row, "filepath", 2, "") or ""
        stored_size = _value(row, "stored_size", 4, None)
        resolved_filepath = None if stored_size is not None else _resolve_upload_path(filepath, filename)
        display_filename = _document_display_name(filename, student_id)
        extension = os.path.splitext(display_filename)[1].lower().lstrip(".") or "file"
        available = stored_size is not None or resolved_filepath is not None
        size = int(stored_size) if stored_size is not None else None
        if size is None and resolved_filepath:
            try:
                size = os.path.getsize(resolved_filepath)
            except OSError:
                size = None
        preview_type = "image" if extension in {"png", "jpg", "jpeg", "gif"} else None
        documents.append(
            {
                "id": document_id,
                "filename": display_filename,
                "extension": extension,
                "size": _format_file_size(size),
                "uploaded_at": _format_datetime(_value(row, "uploaded_at", 3, None)),
                "available": available,
                "preview_type": preview_type,
            }
        )

    memberships = [
        {
            "id": int(_value(row, "id", 0, 0) or 0),
            "name": _value(row, "name", 1, "") or "Classroom",
            "section": _value(row, "section", 2, "") or "",
            "classroom_type": _value(row, "classroom_type", 3, "classroom") or "classroom",
            "archived": bool(int(_value(row, "archived", 4, 0) or 0)),
            "company_name": _value(row, "company_name", 5, "") or "",
        }
        for row in membership_rows
    ]

    return render_template(
        "supervisor/student_document_folder.html",
        student=student,
        documents=documents,
        memberships=memberships,
        active_page="student_documents",
    )


@supervisor_documents.route("/supervisor/student-documents/<int:student_id>/document/<int:document_id>")
@role_required("supervisor")
def view_student_document(student_id, document_id):
    supervisor_id = int(session["user_id"])
    conn = get_db_connection()
    try:
        if not _supervisor_owns_student(conn, supervisor_id, student_id):
            abort(404)
        row = conn.execute(
            """
            SELECT filename, filepath, file_data
            FROM documents
            WHERE id = ? AND student_id = ?
            LIMIT 1
            """,
            (document_id, student_id),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)

    filename = _value(row, "filename", 0, "") or "Document"
    filepath = _value(row, "filepath", 1, "") or ""
    file_data = normalize_document_bytes(_value(row, "file_data", 2, None))
    download = (request.args.get("download") or "").strip() == "1"
    display_name = _document_display_name(filename, student_id)

    if file_data is not None:
        return send_file(
            BytesIO(file_data),
            as_attachment=download,
            download_name=display_name,
        )

    resolved_filepath = _resolve_upload_path(filepath, filename)
    if not resolved_filepath:
        if not _is_safe_upload_path(filepath):
            abort(403)
        abort(404)

    return send_file(
        resolved_filepath,
        as_attachment=download,
        download_name=display_name,
    )
