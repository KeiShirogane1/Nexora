"""Extend Student/Supervisor Trash coverage without changing its schema or routes.

This module is loaded by ``app.Http.Controllers`` before Flask registers the
existing ``admin_trash`` blueprint.  It reuses the existing role_trash_items
store and route/UI endpoints, while widening the recoverable item types and
keeping the original ownership/active-account rules authoritative.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
from datetime import date, datetime, timedelta

from flask import current_app, flash, redirect, request, session, url_for

from app.Models.db import get_db_connection


_trash = importlib.import_module("app.Http.Controllers.admin_trash")
_bp = _trash.admin_trash
_original_render_template = _trash.render_template


def _row_dict(row, keys):
    if row is None:
        return None
    return {key: row[index] for index, key in enumerate(keys)}


def _payload(row):
    try:
        return json.loads(row[6] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _encode_binary(value):
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    elif isinstance(value, bytearray):
        value = bytes(value)
    elif not isinstance(value, bytes):
        try:
            value = bytes(value)
        except (TypeError, ValueError):
            return None
    return base64.b64encode(value).decode("ascii")


def _decode_binary(value):
    if not value:
        return None
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, TypeError):
        return None


def _active_actor(expected_role):
    user_id = session.get("user_id")
    if user_id is None or session.get("role") != expected_role:
        return None
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT role, COALESCE(status, 'active') FROM users WHERE id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        if str(row[0] or "") != expected_role or str(row[1] or "active") == "inactive":
            return None
        return user_id
    finally:
        conn.close()


def _actor_valid(user_id, expected_role):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return False
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT role, COALESCE(status, 'active') FROM users WHERE id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        return bool(
            row
            and str(row[0] or "") == expected_role
            and str(row[1] or "active") != "inactive"
        )
    finally:
        conn.close()


def _upload_cleanup_path(path):
    """Normalize an absolute or UPLOAD_FOLDER-relative path for safe cleanup."""
    if not path:
        return None
    base = current_app.config.get("UPLOAD_FOLDER", "")
    if not base:
        return None
    raw = str(path)
    candidate = raw if os.path.isabs(raw) else os.path.join(base, raw)
    try:
        base_real = os.path.realpath(base)
        target_real = os.path.realpath(candidate)
        if os.path.commonpath([base_real, target_real]) != base_real:
            return None
        return target_real
    except (OSError, ValueError, TypeError):
        return None


def _read_upload_bytes(path, max_bytes):
    target = _upload_cleanup_path(path)
    if not target:
        return None
    try:
        size = os.path.getsize(target)
        if size < 0 or size > max_bytes:
            return None
        with open(target, "rb") as handle:
            data = handle.read(max_bytes + 1)
        return data if len(data) <= max_bytes else None
    except OSError:
        return None


def _read_logbook_photo_bytes(relative_path, max_bytes=8 * 1024 * 1024):
    if not relative_path:
        return None
    try:
        from app.Services.logbook_photo_service import PHOTO_ROOT
        root = PHOTO_ROOT.resolve()
        target = (root / str(relative_path)).resolve()
        if target != root and root not in target.parents:
            return None
        if not target.is_file() or target.stat().st_size > max_bytes:
            return None
        data = target.read_bytes()
        return data if len(data) <= max_bytes else None
    except (OSError, RuntimeError, ValueError, TypeError):
        return None


def _snapshot_logbook(conn, student_id, log_id):
    row = conn.execute(
        """
        SELECT l.id, l.attendance_id, l.student_id, l.content, l.created_at,
               COALESCE(l.entry_type, 'activity'), l.accomplishment, l.reflection,
               l.challenges, l.related_assignment_id, l.updated_at,
               a.status, a.classroom_id, COALESCE(c.name, 'Legacy attendance')
        FROM logs l
        JOIN attendance a ON a.id = l.attendance_id
        LEFT JOIN classrooms c ON c.id = a.classroom_id
        WHERE l.id = ? AND l.student_id = ?
        LIMIT 1
        """,
        (log_id, student_id),
    ).fetchone()
    if not row:
        return None

    log = _row_dict(
        row,
        (
            "id", "attendance_id", "student_id", "content", "created_at",
            "entry_type", "accomplishment", "reflection", "challenges",
            "related_assignment_id", "updated_at", "attendance_status",
            "classroom_id", "classroom_name",
        ),
    )
    links = conn.execute(
        "SELECT log_id, assignment_id, sort_order FROM daily_log_work_links WHERE log_id = ? ORDER BY sort_order, assignment_id",
        (log_id,),
    ).fetchall()
    link_data = [
        _row_dict(item, ("log_id", "assignment_id", "sort_order"))
        for item in links
    ]
    photos = conn.execute(
        """
        SELECT id, log_id, original_filename, stored_filename, relative_path,
               mime_type, size_bytes, file_data, uploaded_at
        FROM logbook_photos
        WHERE log_id = ?
        ORDER BY id
        """,
        (log_id,),
    ).fetchall()
    photo_data = []
    for photo in photos:
        item = _row_dict(
            photo,
            (
                "id", "log_id", "original_filename", "stored_filename",
                "relative_path", "mime_type", "size_bytes", "file_data",
                "uploaded_at",
            ),
        )
        photo_bytes = item.get("file_data")
        if photo_bytes is None:
            photo_bytes = _read_logbook_photo_bytes(item.get("relative_path"))
        item["file_data"] = _encode_binary(photo_bytes)
        photo_data.append(item)
    return {"log": log, "links": link_data, "photos": photo_data}


def _move_student_log_to_role_trash(student_id, log_id):
    if not _actor_valid(student_id, "student"):
        return False, "Your account is not authorized to delete this Logbook entry."

    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        snapshot = _snapshot_logbook(conn, student_id, log_id)
        if not snapshot:
            return False, "Logbook entry not found."
        log = snapshot["log"]
        if str(log.get("attendance_status") or "") != "Open":
            return False, "Previous OJT days are read-only and cannot be moved to Trash."

        _trash._upsert_role_trash_item(
            conn,
            int(student_id),
            "student",
            "logbook",
            int(log_id),
            previous_state=str(log.get("entry_type") or "activity"),
            payload=snapshot,
        )
        conn.execute("DELETE FROM logbook_photos WHERE log_id = ?", (log_id,))
        conn.execute("DELETE FROM daily_log_work_links WHERE log_id = ?", (log_id,))
        conn.execute("DELETE FROM logs WHERE id = ? AND student_id = ?", (log_id, student_id))
        conn.commit()
        return True, "Daily OJT entry moved to Trash."
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to move Daily OJT entry %s to Trash", log_id)
        return False, "Unable to move the Daily OJT entry to Trash."
    finally:
        conn.close()


def _move_supervisor_task_to_role_trash(supervisor_id, task_id):
    if not _actor_valid(supervisor_id, "supervisor"):
        return False, "Your account is not authorized to delete this Task.", None

    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        snapshot = _trash._task_snapshot(conn, task_id, supervisor_id)
        if not snapshot:
            return False, "Task not found or access denied.", None
        task = snapshot["task"]
        _trash._upsert_role_trash_item(
            conn,
            int(supervisor_id),
            "supervisor",
            "task",
            int(task_id),
            previous_state=str(task.get("status") or "Pending"),
            payload=snapshot,
        )
        conn.execute("DELETE FROM task_submissions WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id = ? AND supervisor_id = ?", (task_id, supervisor_id))
        conn.commit()
        return True, "Task moved to Trash.", int(task["student_id"])
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to move Task %s to Trash", task_id)
        return False, "Unable to move the Task to Trash.", None
    finally:
        conn.close()


def _snapshot_work(conn, supervisor_id, class_id, assignment_id):
    assignment_row = conn.execute(
        """
        SELECT a.id, a.classroom_id, a.author_id, a.title, a.description,
               a.due_at, a.points, a.created_at, c.name
        FROM classroom_assignments a
        JOIN classrooms c ON c.id = a.classroom_id
        WHERE a.id = ? AND a.classroom_id = ? AND c.supervisor_id = ?
        LIMIT 1
        """,
        (assignment_id, class_id, supervisor_id),
    ).fetchone()
    if not assignment_row:
        return None

    assignment = _row_dict(
        assignment_row,
        (
            "id", "classroom_id", "author_id", "title", "description",
            "due_at", "points", "created_at", "classroom_name",
        ),
    )
    meta_row = conn.execute(
        """
        SELECT assignment_id, activity_type, external_url, resource_label,
               resource_filename, resource_filepath, allow_file_upload,
               group_mode, max_group_size, team_name, submission_mode
        FROM classroom_assignment_meta
        WHERE assignment_id = ?
        """,
        (assignment_id,),
    ).fetchone()
    meta = _row_dict(
        meta_row,
        (
            "assignment_id", "activity_type", "external_url", "resource_label",
            "resource_filename", "resource_filepath", "allow_file_upload",
            "group_mode", "max_group_size", "team_name", "submission_mode",
        ),
    ) if meta_row else None

    recipients = [
        _row_dict(row, ("id", "assignment_id", "student_id", "created_at"))
        for row in conn.execute(
            "SELECT id, assignment_id, student_id, created_at FROM classroom_assignment_recipients WHERE assignment_id = ? ORDER BY id",
            (assignment_id,),
        ).fetchall()
    ]
    submissions = [
        _row_dict(
            row,
            (
                "id", "assignment_id", "student_id", "attempt_no", "content",
                "status", "submitted_at", "grade", "feedback", "is_team_submission",
            ),
        )
        for row in conn.execute(
            """
            SELECT id, assignment_id, student_id, attempt_no, content, status,
                   submitted_at, grade, feedback, COALESCE(is_team_submission, 0)
            FROM classwork_submissions
            WHERE assignment_id = ? ORDER BY id
            """,
            (assignment_id,),
        ).fetchall()
    ]
    submission_files = [
        _row_dict(
            row,
            (
                "id", "submission_id", "original_filename", "stored_filename",
                "relative_path", "mime_type", "size_bytes", "created_at",
            ),
        )
        for row in conn.execute(
            """
            SELECT f.id, f.submission_id, f.original_filename, f.stored_filename,
                   f.relative_path, f.mime_type, f.size_bytes, f.created_at
            FROM classwork_submission_files f
            JOIN classwork_submissions s ON s.id = f.submission_id
            WHERE s.assignment_id = ? ORDER BY f.id
            """,
            (assignment_id,),
        ).fetchall()
    ]
    scores = [
        _row_dict(
            row,
            (
                "id", "assignment_id", "student_id", "score", "max_score",
                "percentage", "grading_method", "imported_at",
            ),
        )
        for row in conn.execute(
            """
            SELECT id, assignment_id, student_id, score, max_score, percentage,
                   grading_method, imported_at
            FROM classwork_scores
            WHERE assignment_id = ? ORDER BY id
            """,
            (assignment_id,),
        ).fetchall()
    ]
    legacy_submissions = [
        _row_dict(
            row,
            (
                "id", "assignment_id", "student_id", "content", "filename",
                "filepath", "submitted_at", "status", "grade", "feedback",
            ),
        )
        for row in conn.execute(
            """
            SELECT id, assignment_id, student_id, content, filename, filepath,
                   submitted_at, status, grade, feedback
            FROM classroom_submissions
            WHERE assignment_id = ? ORDER BY id
            """,
            (assignment_id,),
        ).fetchall()
    ]
    work_links = [
        _row_dict(row, ("log_id", "assignment_id", "sort_order"))
        for row in conn.execute(
            "SELECT log_id, assignment_id, sort_order FROM daily_log_work_links WHERE assignment_id = ? ORDER BY log_id, sort_order",
            (assignment_id,),
        ).fetchall()
    ]
    legacy_log_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM logs WHERE related_assignment_id = ? ORDER BY id",
            (assignment_id,),
        ).fetchall()
    ]
    return {
        "assignment": assignment,
        "meta": meta,
        "recipients": recipients,
        "submissions": submissions,
        "submission_files": submission_files,
        "scores": scores,
        "legacy_submissions": legacy_submissions,
        "work_links": work_links,
        "legacy_log_ids": legacy_log_ids,
    }


def _move_work(supervisor_id, class_id, assignment_id):
    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        snapshot = _snapshot_work(conn, supervisor_id, class_id, assignment_id)
        if not snapshot:
            return False, "Work not found or access denied."

        _trash._upsert_role_trash_item(
            conn,
            supervisor_id,
            "supervisor",
            "work",
            assignment_id,
            payload=snapshot,
        )
        conn.execute("UPDATE logs SET related_assignment_id = NULL WHERE related_assignment_id = ?", (assignment_id,))
        conn.execute("DELETE FROM daily_log_work_links WHERE assignment_id = ?", (assignment_id,))
        conn.execute(
            "DELETE FROM classwork_submission_files WHERE submission_id IN (SELECT id FROM classwork_submissions WHERE assignment_id = ?)",
            (assignment_id,),
        )
        conn.execute("DELETE FROM classwork_submissions WHERE assignment_id = ?", (assignment_id,))
        conn.execute("DELETE FROM classwork_scores WHERE assignment_id = ?", (assignment_id,))
        conn.execute("DELETE FROM classroom_submissions WHERE assignment_id = ?", (assignment_id,))
        conn.execute("DELETE FROM classroom_assignment_recipients WHERE assignment_id = ?", (assignment_id,))
        conn.execute("DELETE FROM classroom_assignment_meta WHERE assignment_id = ?", (assignment_id,))
        conn.execute(
            "DELETE FROM classroom_assignments WHERE id = ? AND classroom_id = ?",
            (assignment_id, class_id),
        )
        conn.commit()
        return True, "Work moved to Trash. Existing Daily OJT Logbook entries were preserved."
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to move Work %s to Trash", assignment_id)
        return False, "Unable to move Work to Trash."
    finally:
        conn.close()


def _move_membership(owner_user_id, owner_role, class_id, student_id):
    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        if owner_role == "supervisor":
            classroom = conn.execute(
                "SELECT id, name, supervisor_id FROM classrooms WHERE id = ? AND supervisor_id = ? LIMIT 1",
                (class_id, owner_user_id),
            ).fetchone()
            if not classroom:
                return False, "Classroom not found or access denied.", None
        else:
            classroom = conn.execute(
                "SELECT id, name, supervisor_id FROM classrooms WHERE id = ? LIMIT 1",
                (class_id,),
            ).fetchone()
            if not classroom or int(student_id) != int(owner_user_id):
                return False, "Intern Classroom membership not found.", None
            open_attendance = conn.execute(
                "SELECT id FROM attendance WHERE student_id = ? AND status = 'Open' LIMIT 1",
                (student_id,),
            ).fetchone()
            if open_attendance:
                return False, "You must Clock Out before leaving your Intern Classroom.", None

        membership = conn.execute(
            """
            SELECT id, classroom_id, student_id, joined_at
            FROM classroom_students
            WHERE classroom_id = ? AND student_id = ?
            LIMIT 1
            """,
            (class_id, student_id),
        ).fetchone()
        if not membership:
            return False, "Student is not enrolled in this class.", None

        membership_data = _row_dict(
            membership,
            ("id", "classroom_id", "student_id", "joined_at"),
        )
        student_row = conn.execute("SELECT username FROM users WHERE id = ?", (student_id,)).fetchone()
        payload = {
            "membership": membership_data,
            "classroom_name": str(classroom[1] or "Classroom"),
            "supervisor_id": int(classroom[2]),
            "student_name": str(student_row[0] if student_row else "Student"),
        }
        _trash._upsert_role_trash_item(
            conn,
            owner_user_id,
            owner_role,
            "classroom_membership",
            int(membership_data["id"]),
            payload=payload,
        )
        conn.execute(
            "DELETE FROM classroom_students WHERE classroom_id = ? AND student_id = ?",
            (class_id, student_id),
        )
        conn.commit()
        return True, "Classroom membership moved to Trash.", payload
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to move classroom membership to Trash")
        return False, "Unable to remove the classroom membership.", None
    finally:
        conn.close()


def _move_document(student_id, document_id):
    try:
        from app.Services.document_storage import ensure_document_storage_schema
        ensure_document_storage_schema()
    except Exception:
        current_app.logger.exception("Unable to initialize document storage before Trash move")
        return False, "Document storage is unavailable."

    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        row = conn.execute(
            """
            SELECT id, student_id, filename, filepath, uploaded_at, file_data
            FROM documents
            WHERE id = ? AND student_id = ?
            LIMIT 1
            """,
            (document_id, student_id),
        ).fetchone()
        if not row:
            return False, "Document not found."
        document = _row_dict(row, ("id", "student_id", "filename", "filepath", "uploaded_at", "file_data"))
        document_bytes = document.get("file_data")
        if document_bytes is None:
            document_bytes = _read_upload_bytes(document.get("filepath"), 5 * 1024 * 1024)
        document["file_data"] = _encode_binary(document_bytes)
        _trash._upsert_role_trash_item(
            conn, student_id, "student", "document", document_id, payload={"document": document}
        )
        conn.execute("DELETE FROM documents WHERE id = ? AND student_id = ?", (document_id, student_id))
        conn.commit()
        return True, "Document moved to Trash."
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to move document %s to Trash", document_id)
        return False, "Unable to move the document to Trash."
    finally:
        conn.close()


def _move_task_submission(student_id, submission_id):
    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        row = conn.execute(
            """
            SELECT ts.id, ts.task_id, ts.filename, ts.filepath, ts.submitted_at, ts.remarks,
                   t.task_title
            FROM task_submissions ts
            JOIN tasks t ON t.id = ts.task_id
            WHERE ts.id = ? AND t.student_id = ?
            LIMIT 1
            """,
            (submission_id, student_id),
        ).fetchone()
        if not row:
            return False, "Submission not found.", None
        submission = _row_dict(
            row,
            ("id", "task_id", "filename", "filepath", "submitted_at", "remarks", "task_title"),
        )
        _trash._upsert_role_trash_item(
            conn,
            student_id,
            "student",
            "task_submission",
            submission_id,
            payload={"submission": submission},
        )
        conn.execute("DELETE FROM task_submissions WHERE id = ?", (submission_id,))
        conn.commit()
        return True, "Submission moved to Trash.", int(submission["task_id"])
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to move task submission %s to Trash", submission_id)
        return False, "Unable to move the submission to Trash.", None
    finally:
        conn.close()


def _move_logbook_photo(student_id, photo_id):
    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        row = conn.execute(
            """
            SELECT p.id, p.log_id, p.original_filename, p.stored_filename,
                   p.relative_path, p.mime_type, p.size_bytes, p.file_data,
                   p.uploaded_at, l.attendance_id, a.classroom_id
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
            return False, "Photo evidence can only be removed from your open Daily OJT entry.", None
        photo = _row_dict(
            row,
            (
                "id", "log_id", "original_filename", "stored_filename", "relative_path",
                "mime_type", "size_bytes", "file_data", "uploaded_at", "attendance_id",
                "classroom_id",
            ),
        )
        photo_bytes = photo.get("file_data")
        if photo_bytes is None:
            photo_bytes = _read_logbook_photo_bytes(photo.get("relative_path"))
        photo["file_data"] = _encode_binary(photo_bytes)
        _trash._upsert_role_trash_item(
            conn,
            student_id,
            "student",
            "logbook_photo",
            photo_id,
            payload={"photo": photo},
        )
        conn.execute("DELETE FROM logbook_photos WHERE id = ?", (photo_id,))
        conn.commit()
        return True, "Photo evidence moved to Trash.", photo
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to move logbook photo %s to Trash", photo_id)
        return False, "Unable to move photo evidence to Trash.", None
    finally:
        conn.close()


def _move_notifications(user_id, notification_ids):
    ids = []
    seen = set()
    for raw_id in notification_ids:
        try:
            notification_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if notification_id > 0 and notification_id not in seen:
            seen.add(notification_id)
            ids.append(notification_id)

    if not ids:
        return 0

    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        moved = 0
        for notification_id in ids:
            row = conn.execute(
                """
                SELECT id, user_id, title, message, notification_type,
                       is_read, link_url, created_at
                FROM notifications
                WHERE id = ? AND user_id = ?
                LIMIT 1
                """,
                (notification_id, user_id),
            ).fetchone()
            if not row:
                continue
            notification = _row_dict(
                row,
                ("id", "user_id", "title", "message", "notification_type", "is_read", "link_url", "created_at"),
            )
            _trash._upsert_role_trash_item(
                conn,
                user_id,
                str(session.get("role")),
                "notification",
                notification_id,
                payload={"notification": notification},
            )
            conn.execute("DELETE FROM notifications WHERE id = ? AND user_id = ?", (notification_id, user_id))
            moved += 1
        conn.commit()
        return moved
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to move notifications to Trash")
        return 0
    finally:
        conn.close()


def _notification_ids_for_date(user_id, target_date):
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM notifications WHERE user_id = ? AND created_at >= ? AND created_at < ? ORDER BY id",
            (user_id, day_start, day_end),
        ).fetchall()
        return [int(row[0]) for row in rows]
    finally:
        conn.close()


def _item_card(row, owner_role, conn):
    trash_id = int(row[0])
    item_type = str(row[3])
    previous_state = row[5]
    data = _payload(row)
    deleted_at = _trash._role_trash_datetime(row[7])
    expires_at = _trash._role_trash_datetime(row[8])
    now = datetime.now()
    days_left = max(0, (expires_at.date() - now.date()).days) if expires_at else 0

    type_label = "Deleted Item"
    title = "Recoverable item"
    subtitle = "Restore this item or delete it permanently."

    if item_type == "logbook":
        log = data.get("log") or {}
        type_label = "Logbook"
        title = "Daily OJT Logbook Entry"
        content = str(log.get("content") or log.get("accomplishment") or "Daily OJT entry").strip()
        snippet = content if len(content) <= 100 else f"{content[:97]}..."
        subtitle = f"{log.get('classroom_name') or 'Legacy attendance'} · {snippet}"
    elif item_type == "document":
        document = data.get("document") or {}
        type_label = "Document"
        filename = str(document.get("filename") or "Document")
        prefix = f"{int(row[1])}_"
        title = filename[len(prefix):] if filename.startswith(prefix) else filename
        subtitle = "Student document"
    elif item_type == "task_submission":
        submission = data.get("submission") or {}
        type_label = "Submission"
        title = str(submission.get("filename") or "Task submission")
        subtitle = str(submission.get("task_title") or "Assigned Task")
    elif item_type == "logbook_photo":
        photo = data.get("photo") or {}
        type_label = "Photo"
        title = str(photo.get("original_filename") or "OJT photo evidence")
        subtitle = "Daily OJT Logbook photo evidence"
    elif item_type == "classroom_membership":
        membership = data.get("membership") or {}
        type_label = "Enrollment"
        title = str(data.get("classroom_name") or "Intern Classroom")
        if owner_role == "supervisor":
            subtitle = f"Removed intern: {data.get('student_name') or _trash._student_name(conn, membership.get('student_id'))}"
        else:
            subtitle = "Classroom membership"
    elif item_type == "notification":
        notification = data.get("notification") or {}
        type_label = "Notification"
        title = str(notification.get("title") or "Notification")
        message = str(notification.get("message") or "").strip()
        subtitle = message if len(message) <= 110 else f"{message[:107]}..."
    elif item_type == "task":
        task = data.get("task") or {}
        type_label = "Task"
        title = str(task.get("task_title") or "Assigned Task")
        student_name = _trash._student_name(conn, task.get("student_id")) if task.get("student_id") else "Student"
        status = str(task.get("status") or previous_state or "Pending")
        subtitle = f"{student_name} · Previous status: {status}"
    elif item_type == "work":
        assignment = data.get("assignment") or {}
        meta = data.get("meta") or {}
        type_label = "Work"
        title = str(assignment.get("title") or "Classroom Work")
        work_type = str(meta.get("activity_type") or "assignment").replace("_", " ").title()
        subtitle = f"{assignment.get('classroom_name') or 'Intern Classroom'} · {work_type}"

    endpoint_prefix = "student" if owner_role == "student" else "supervisor"
    return {
        "id": trash_id,
        "item_type": item_type,
        "type_label": type_label,
        "title": title,
        "subtitle": subtitle,
        "deleted_label": _trash._role_trash_label(deleted_at),
        "expires_label": _trash._role_trash_label(expires_at),
        "days_left": days_left,
        "restore_url": url_for(f"admin_trash.{endpoint_prefix}_trash_restore", trash_id=trash_id),
        "permanent_url": url_for(f"admin_trash.{endpoint_prefix}_trash_permanent", trash_id=trash_id),
    }


def _list_role_trash(owner_user_id, owner_role):
    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        _trash._purge_expired_role_trash(conn, owner_user_id, owner_role)
        rows = conn.execute(
            """
            SELECT id, owner_user_id, owner_role, item_type, item_id,
                   previous_state, payload, deleted_at, expires_at
            FROM role_trash_items
            WHERE owner_user_id = ? AND owner_role = ?
            ORDER BY deleted_at DESC, id DESC
            """,
            (owner_user_id, owner_role),
        ).fetchall()
        items = [_item_card(row, owner_role, conn) for row in rows]
        expiring_soon = sum(1 for item in items if item["days_left"] <= 7)
        return items, expiring_soon
    finally:
        conn.close()


def _restore_logbook(conn, owner_user_id, row, data):
    log = data.get("log") or {}
    item_id = int(row[4])
    if not log:
        active = conn.execute(
            "SELECT attendance_id FROM logs WHERE id = ? AND student_id = ? LIMIT 1",
            (item_id, owner_user_id),
        ).fetchone()
        if not active:
            return False, "That Logbook entry no longer exists."
        previous_state = str(row[5] or "daily")
        if previous_state == "daily":
            conflict = conn.execute(
                "SELECT 1 FROM logs WHERE attendance_id = ? AND student_id = ? AND entry_type = 'daily' AND id != ? LIMIT 1",
                (active[0], owner_user_id, item_id),
            ).fetchone()
            if conflict:
                return False, "A replacement Daily OJT entry already exists for that attendance day."
        conn.execute(
            "UPDATE logs SET entry_type = ? WHERE id = ? AND student_id = ?",
            (previous_state, item_id, owner_user_id),
        )
        return True, "Daily OJT entry restored successfully."

    attendance_id = int(log.get("attendance_id") or 0)
    attendance = conn.execute(
        "SELECT 1 FROM attendance WHERE id = ? AND student_id = ? LIMIT 1",
        (attendance_id, owner_user_id),
    ).fetchone()
    if not attendance:
        return False, "The original attendance session no longer exists."
    if conn.execute("SELECT 1 FROM logs WHERE id = ? LIMIT 1", (item_id,)).fetchone():
        return False, "That Logbook entry ID is already active and cannot be restored."
    entry_type = str(log.get("entry_type") or row[5] or "activity")
    if entry_type == "daily":
        conflict = conn.execute(
            "SELECT 1 FROM logs WHERE attendance_id = ? AND student_id = ? AND entry_type = 'daily' LIMIT 1",
            (attendance_id, owner_user_id),
        ).fetchone()
        if conflict:
            return False, "A replacement Daily OJT entry already exists for that attendance day."

    related_assignment_id = log.get("related_assignment_id")
    if related_assignment_id and not conn.execute(
        "SELECT 1 FROM classroom_assignments WHERE id = ? LIMIT 1", (related_assignment_id,)
    ).fetchone():
        related_assignment_id = None

    conn.execute(
        """
        INSERT INTO logs (
            id, attendance_id, student_id, content, created_at, entry_type,
            accomplishment, reflection, challenges, related_assignment_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            attendance_id,
            owner_user_id,
            log.get("content") or log.get("accomplishment") or "Recovered Daily OJT entry",
            log.get("created_at"),
            entry_type,
            log.get("accomplishment"),
            log.get("reflection"),
            log.get("challenges"),
            related_assignment_id,
            log.get("updated_at"),
        ),
    )
    for link in data.get("links", []) or []:
        assignment_id = link.get("assignment_id")
        if not assignment_id or not conn.execute(
            "SELECT 1 FROM classroom_assignments WHERE id = ? LIMIT 1", (assignment_id,)
        ).fetchone():
            continue
        conn.execute(
            "INSERT INTO daily_log_work_links (log_id, assignment_id, sort_order) VALUES (?, ?, ?)",
            (item_id, int(assignment_id), int(link.get("sort_order") or 0)),
        )
    for photo in data.get("photos", []) or []:
        conn.execute(
            """
            INSERT INTO logbook_photos (
                id, log_id, original_filename, stored_filename, relative_path,
                mime_type, size_bytes, file_data, uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(photo["id"]),
                item_id,
                photo.get("original_filename") or "photo",
                photo.get("stored_filename") or "photo",
                photo.get("relative_path") or "",
                photo.get("mime_type") or "image/jpeg",
                int(photo.get("size_bytes") or 0),
                _decode_binary(photo.get("file_data")),
                photo.get("uploaded_at"),
            ),
        )
    return True, "Daily OJT entry restored successfully."


def _restore_task(conn, owner_user_id, row, data):
    task = data.get("task") or {}
    item_id = int(row[4])
    if not task or int(task.get("supervisor_id") or 0) != int(owner_user_id):
        return False, "Task recovery data is incomplete."
    if conn.execute("SELECT 1 FROM tasks WHERE id = ? LIMIT 1", (item_id,)).fetchone():
        return False, "That task ID is already active and cannot be restored."
    if not conn.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1", (task.get("student_id"),)).fetchone():
        return False, "The original student account no longer exists."
    conn.execute(
        """
        INSERT INTO tasks (
            id, student_id, supervisor_id, task_title, task_description,
            assigned_at, deadline, requires_submission, allow_late_submission, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(task.get("id") or item_id), int(task["student_id"]), owner_user_id,
            task.get("task_title") or "Recovered Task", task.get("task_description"),
            task.get("assigned_at"), task.get("deadline"),
            int(task.get("requires_submission") or 0),
            int(task.get("allow_late_submission") or 0),
            task.get("status") or row[5] or "Pending",
        ),
    )
    for submission in data.get("submissions", []) or []:
        conn.execute(
            "INSERT INTO task_submissions (id, task_id, filename, filepath, submitted_at, remarks) VALUES (?, ?, ?, ?, ?, ?)",
            (
                int(submission["id"]), item_id,
                submission.get("filename") or "Recovered submission",
                submission.get("filepath") or "",
                submission.get("submitted_at"), submission.get("remarks"),
            ),
        )
    return True, "Task restored successfully."


def _restore_work(conn, owner_user_id, row, data):
    assignment = data.get("assignment") or {}
    item_id = int(row[4])
    class_id = int(assignment.get("classroom_id") or 0)
    classroom = conn.execute(
        "SELECT 1 FROM classrooms WHERE id = ? AND supervisor_id = ? LIMIT 1",
        (class_id, owner_user_id),
    ).fetchone()
    if not classroom:
        return False, "The original Intern Classroom no longer exists or is no longer yours."
    if conn.execute("SELECT 1 FROM classroom_assignments WHERE id = ? LIMIT 1", (item_id,)).fetchone():
        return False, "That Work ID is already active and cannot be restored."

    dependent_students = set()
    for group in (data.get("recipients", []), data.get("submissions", []), data.get("legacy_submissions", []), data.get("scores", [])):
        for item in group or []:
            if item.get("student_id"):
                dependent_students.add(int(item["student_id"]))
    for student_id in dependent_students:
        if not conn.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1", (student_id,)).fetchone():
            return False, "A student referenced by this Work no longer exists, so it cannot be restored safely."

    conn.execute(
        """
        INSERT INTO classroom_assignments (id, classroom_id, author_id, title, description, due_at, points, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id, class_id, int(owner_user_id),
            assignment.get("title") or "Recovered Work", assignment.get("description"),
            assignment.get("due_at"), int(assignment.get("points") or 0), assignment.get("created_at"),
        ),
    )
    meta = data.get("meta")
    if meta:
        conn.execute(
            """
            INSERT INTO classroom_assignment_meta (
                assignment_id, activity_type, external_url, resource_label,
                resource_filename, resource_filepath, allow_file_upload,
                group_mode, max_group_size, team_name, submission_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id, meta.get("activity_type") or "assignment", meta.get("external_url"),
                meta.get("resource_label"), meta.get("resource_filename"), meta.get("resource_filepath"),
                int(meta.get("allow_file_upload") or 0), int(meta.get("group_mode") or 0),
                int(meta.get("max_group_size") or 1), meta.get("team_name"),
                meta.get("submission_mode") or "individual",
            ),
        )
    for recipient in data.get("recipients", []) or []:
        conn.execute(
            "INSERT INTO classroom_assignment_recipients (id, assignment_id, student_id, created_at) VALUES (?, ?, ?, ?)",
            (int(recipient["id"]), item_id, int(recipient["student_id"]), recipient.get("created_at")),
        )
    for submission in data.get("submissions", []) or []:
        conn.execute(
            """
            INSERT INTO classwork_submissions (
                id, assignment_id, student_id, attempt_no, content, status,
                submitted_at, grade, feedback, is_team_submission
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(submission["id"]), item_id, int(submission["student_id"]),
                int(submission.get("attempt_no") or 1), submission.get("content"),
                submission.get("status") or "submitted", submission.get("submitted_at"),
                submission.get("grade"), submission.get("feedback"),
                int(submission.get("is_team_submission") or 0),
            ),
        )
    for file_item in data.get("submission_files", []) or []:
        conn.execute(
            """
            INSERT INTO classwork_submission_files (
                id, submission_id, original_filename, stored_filename,
                relative_path, mime_type, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(file_item["id"]), int(file_item["submission_id"]),
                file_item.get("original_filename") or "submission",
                file_item.get("stored_filename") or "submission",
                file_item.get("relative_path") or "", file_item.get("mime_type"),
                int(file_item.get("size_bytes") or 0), file_item.get("created_at"),
            ),
        )
    for score in data.get("scores", []) or []:
        conn.execute(
            """
            INSERT INTO classwork_scores (
                id, assignment_id, student_id, score, max_score, percentage,
                grading_method, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(score["id"]), item_id, int(score["student_id"]), score.get("score"),
                score.get("max_score"), score.get("percentage"),
                score.get("grading_method") or "imported", score.get("imported_at"),
            ),
        )
    for submission in data.get("legacy_submissions", []) or []:
        conn.execute(
            """
            INSERT INTO classroom_submissions (
                id, assignment_id, student_id, content, filename, filepath,
                submitted_at, status, grade, feedback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(submission["id"]), item_id, int(submission["student_id"]),
                submission.get("content"), submission.get("filename"), submission.get("filepath"),
                submission.get("submitted_at"), submission.get("status") or "submitted",
                submission.get("grade"), submission.get("feedback"),
            ),
        )
    for link in data.get("work_links", []) or []:
        log_id = int(link.get("log_id") or 0)
        if log_id and conn.execute("SELECT 1 FROM logs WHERE id = ? LIMIT 1", (log_id,)).fetchone():
            conn.execute(
                "INSERT INTO daily_log_work_links (log_id, assignment_id, sort_order) VALUES (?, ?, ?)",
                (log_id, item_id, int(link.get("sort_order") or 0)),
            )
    for log_id in data.get("legacy_log_ids", []) or []:
        conn.execute(
            "UPDATE logs SET related_assignment_id = ? WHERE id = ? AND related_assignment_id IS NULL",
            (item_id, int(log_id)),
        )
    return True, "Work restored successfully."


def _restore_misc(conn, owner_user_id, owner_role, row, data):
    item_type = str(row[3])
    item_id = int(row[4])
    if item_type == "document" and owner_role == "student":
        document = data.get("document") or {}
        if conn.execute("SELECT 1 FROM documents WHERE id = ? LIMIT 1", (item_id,)).fetchone():
            return False, "That document ID is already active and cannot be restored."
        conn.execute(
            "INSERT INTO documents (id, student_id, filename, filepath, uploaded_at, file_data) VALUES (?, ?, ?, ?, ?, ?)",
            (
                item_id, owner_user_id, document.get("filename") or "Recovered document",
                document.get("filepath") or "", document.get("uploaded_at"),
                _decode_binary(document.get("file_data")),
            ),
        )
        return True, "Document restored successfully."

    if item_type == "task_submission" and owner_role == "student":
        submission = data.get("submission") or {}
        task_id = int(submission.get("task_id") or 0)
        if not conn.execute("SELECT 1 FROM tasks WHERE id = ? AND student_id = ? LIMIT 1", (task_id, owner_user_id)).fetchone():
            return False, "The original Task no longer exists."
        if conn.execute("SELECT 1 FROM task_submissions WHERE id = ? LIMIT 1", (item_id,)).fetchone():
            return False, "That submission ID is already active and cannot be restored."
        conn.execute(
            "INSERT INTO task_submissions (id, task_id, filename, filepath, submitted_at, remarks) VALUES (?, ?, ?, ?, ?, ?)",
            (
                item_id, task_id, submission.get("filename") or "Recovered submission",
                submission.get("filepath") or "", submission.get("submitted_at"), submission.get("remarks"),
            ),
        )
        return True, "Submission restored successfully."

    if item_type == "logbook_photo" and owner_role == "student":
        photo = data.get("photo") or {}
        log_id = int(photo.get("log_id") or 0)
        log = conn.execute(
            """
            SELECT 1 FROM logs l JOIN attendance a ON a.id = l.attendance_id
            WHERE l.id = ? AND l.student_id = ? AND l.entry_type = 'daily' AND a.status = 'Open' LIMIT 1
            """,
            (log_id, owner_user_id),
        ).fetchone()
        if not log:
            return False, "Restore the open Daily OJT entry before restoring this photo."
        count_row = conn.execute("SELECT COUNT(*) FROM logbook_photos WHERE log_id = ?", (log_id,)).fetchone()
        if int(count_row[0] if count_row else 0) >= 5:
            return False, "That Daily OJT entry already has the maximum of 5 photos."
        if conn.execute("SELECT 1 FROM logbook_photos WHERE id = ? LIMIT 1", (item_id,)).fetchone():
            return False, "That photo ID is already active and cannot be restored."
        conn.execute(
            """
            INSERT INTO logbook_photos (
                id, log_id, original_filename, stored_filename, relative_path,
                mime_type, size_bytes, file_data, uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id, log_id, photo.get("original_filename") or "photo",
                photo.get("stored_filename") or "photo", photo.get("relative_path") or "",
                photo.get("mime_type") or "image/jpeg", int(photo.get("size_bytes") or 0),
                _decode_binary(photo.get("file_data")), photo.get("uploaded_at"),
            ),
        )
        return True, "Photo evidence restored successfully."

    if item_type == "classroom_membership":
        membership = data.get("membership") or {}
        class_id = int(membership.get("classroom_id") or 0)
        student_id = int(membership.get("student_id") or 0)
        if owner_role == "student" and student_id != int(owner_user_id):
            return False, "This enrollment does not belong to your account."
        if owner_role == "supervisor" and not conn.execute(
            "SELECT 1 FROM classrooms WHERE id = ? AND supervisor_id = ? LIMIT 1",
            (class_id, owner_user_id),
        ).fetchone():
            return False, "The original Classroom no longer exists or is no longer yours."
        if owner_role == "student" and not conn.execute(
            "SELECT 1 FROM classrooms WHERE id = ? LIMIT 1", (class_id,)
        ).fetchone():
            return False, "The original Classroom no longer exists."
        if not conn.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1", (student_id,)).fetchone():
            return False, "The student account no longer exists."
        if conn.execute(
            "SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ? LIMIT 1",
            (class_id, student_id),
        ).fetchone():
            return False, "That classroom membership is already active."

        target = conn.execute(
            """
            SELECT COALESCE(c.classroom_type, 'classroom'), COALESCE(c.archived, 0),
                   CASE WHEN cid.classroom_id IS NULL THEN 0 ELSE 1 END
            FROM classrooms c
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.id = ?
            LIMIT 1
            """,
            (class_id,),
        ).fetchone()
        target_is_active_internship = bool(
            target
            and not int(target[1] or 0)
            and (str(target[0] or "classroom") == "internship" or int(target[2] or 0) == 1)
        )
        if target_is_active_internship:
            other_active = conn.execute(
                """
                SELECT 1
                FROM classroom_students cs
                JOIN classrooms c ON c.id = cs.classroom_id
                LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
                WHERE cs.student_id = ?
                  AND cs.classroom_id != ?
                  AND COALESCE(c.archived, 0) = 0
                  AND (
                        COALESCE(c.classroom_type, 'classroom') = 'internship'
                        OR cid.classroom_id IS NOT NULL
                  )
                LIMIT 1
                """,
                (student_id, class_id),
            ).fetchone()
            if other_active:
                return False, "The student already belongs to another active Intern Classroom."

        conn.execute(
            "INSERT INTO classroom_students (classroom_id, student_id, joined_at) VALUES (?, ?, ?)",
            (class_id, student_id, membership.get("joined_at")),
        )
        return True, "Classroom membership restored successfully."

    if item_type == "notification":
        notification = data.get("notification") or {}
        if int(notification.get("user_id") or 0) != int(owner_user_id):
            return False, "This notification does not belong to your account."
        if conn.execute("SELECT 1 FROM notifications WHERE id = ? LIMIT 1", (item_id,)).fetchone():
            return False, "That notification ID is already active and cannot be restored."
        conn.execute(
            """
            INSERT INTO notifications (
                id, user_id, title, message, notification_type, is_read, link_url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id, owner_user_id, notification.get("title") or "Recovered notification",
                notification.get("message") or "Recovered notification",
                notification.get("notification_type") or "info",
                int(notification.get("is_read") or 0), notification.get("link_url"),
                notification.get("created_at"),
            ),
        )
        return True, "Notification restored successfully."

    return False, "This Trash item is not valid for your account."


def _restore_role_trash_item(owner_user_id, owner_role, trash_id):
    if not _actor_valid(owner_user_id, owner_role):
        return False, "Your account is not authorized to restore this item."
    conn = get_db_connection()
    try:
        _trash.ensure_role_trash_schema(conn)
        row = conn.execute(
            """
            SELECT id, owner_user_id, owner_role, item_type, item_id,
                   previous_state, payload, deleted_at, expires_at
            FROM role_trash_items
            WHERE id = ? AND owner_user_id = ? AND owner_role = ?
            LIMIT 1
            """,
            (trash_id, owner_user_id, owner_role),
        ).fetchone()
        if not row:
            return False, "Trash item not found."
        if _trash._role_trash_datetime(row[8]) and _trash._role_trash_datetime(row[8]) <= datetime.now():
            cleanup = _purge_role_trash_row(conn, row)
            conn.commit()
            for kind, path in cleanup:
                if kind == "photo":
                    _trash._safe_remove_logbook_photo(path)
                else:
                    _trash._safe_remove_upload(path)
            return False, "That Trash item has expired."

        data = _payload(row)
        item_type = str(row[3])
        if item_type == "logbook" and owner_role == "student":
            ok, message = _restore_logbook(conn, owner_user_id, row, data)
        elif item_type == "task" and owner_role == "supervisor":
            ok, message = _restore_task(conn, owner_user_id, row, data)
        elif item_type == "work" and owner_role == "supervisor":
            ok, message = _restore_work(conn, owner_user_id, row, data)
        else:
            ok, message = _restore_misc(conn, owner_user_id, owner_role, row, data)
        if not ok:
            conn.rollback()
            return False, message

        conn.execute("DELETE FROM role_trash_items WHERE id = ?", (trash_id,))
        conn.commit()
        return True, message
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Unable to restore role Trash item %s", trash_id)
        return False, "Unable to restore this item because related data has changed."
    finally:
        conn.close()


def _purge_role_trash_row(conn, row):
    trash_id = int(row[0])
    owner_user_id = int(row[1])
    owner_role = str(row[2])
    item_type = str(row[3])
    item_id = int(row[4])
    data = _payload(row)
    cleanup = []

    if item_type == "logbook" and owner_role == "student":
        log = data.get("log") or {}
        if log:
            for photo in data.get("photos", []) or []:
                if photo.get("relative_path"):
                    cleanup.append(("photo", photo["relative_path"]))
        else:
            try:
                photos = conn.execute("SELECT relative_path FROM logbook_photos WHERE log_id = ?", (item_id,)).fetchall()
                cleanup.extend(("photo", photo[0]) for photo in photos if photo[0])
            except Exception:
                pass
            conn.execute("DELETE FROM logs WHERE id = ? AND student_id = ?", (item_id, owner_user_id))
    elif item_type == "task" and owner_role == "supervisor":
        for submission in data.get("submissions", []) or []:
            path = _upload_cleanup_path(submission.get("filepath"))
            if path:
                cleanup.append(("upload", path))
    elif item_type == "work" and owner_role == "supervisor":
        meta = data.get("meta") or {}
        path = _upload_cleanup_path(meta.get("resource_filepath"))
        if path:
            cleanup.append(("upload", path))
        for file_item in data.get("submission_files", []) or []:
            path = _upload_cleanup_path(file_item.get("relative_path"))
            if path:
                cleanup.append(("upload", path))
        for submission in data.get("legacy_submissions", []) or []:
            path = _upload_cleanup_path(submission.get("filepath"))
            if path:
                cleanup.append(("upload", path))
    elif item_type == "document" and owner_role == "student":
        path = _upload_cleanup_path((data.get("document") or {}).get("filepath"))
        if path:
            cleanup.append(("upload", path))
    elif item_type == "task_submission" and owner_role == "student":
        path = _upload_cleanup_path((data.get("submission") or {}).get("filepath"))
        if path:
            cleanup.append(("upload", path))
    elif item_type == "logbook_photo" and owner_role == "student":
        path = (data.get("photo") or {}).get("relative_path")
        if path:
            cleanup.append(("photo", path))

    conn.execute("DELETE FROM role_trash_items WHERE id = ?", (trash_id,))
    return cleanup


def _role_trash_render(template_name, **context):
    if template_name == "shared/role_trash.html":
        role = context.get("trash_role")
        context["trash_item_label"] = "Deleted Items"
        if role == "student":
            context["trash_description"] = "Deleted Logbook entries, documents, submissions, photos, classroom memberships, and notifications remain recoverable for 30 days."
            context["trash_empty_copy"] = "Items you delete or remove will appear here for up to 30 days."
        elif role == "supervisor":
            context["trash_description"] = "Deleted Work, assigned Tasks, classroom memberships, and notifications remain recoverable for 30 days."
            context["trash_empty_copy"] = "Items you delete or remove will appear here for up to 30 days."
    return _original_render_template(template_name, **context)


def _notify_membership_change(payload, owner_role, restored=False):
    if not payload:
        return
    try:
        from app.Services.notification_service import create_notification
        membership = payload.get("membership") or {}
        class_id = int(membership.get("classroom_id") or 0)
        student_id = int(membership.get("student_id") or 0)
        class_name = payload.get("classroom_name") or "Classroom"
        student_name = payload.get("student_name") or "Student"
        supervisor_id = int(payload.get("supervisor_id") or 0)
        if restored:
            return
        if owner_role == "student" and supervisor_id:
            create_notification(
                supervisor_id,
                "Intern Left Classroom",
                f"{student_name} left your Intern Classroom {class_name}.",
                "classroom",
                link_url=f"/supervisor/classes/{class_id}",
            )
        elif owner_role == "supervisor" and student_id:
            create_notification(
                student_id,
                "Removed from Class",
                f"You were removed from {class_name}.",
                "classroom",
                link_url="/student/classes",
            )
    except Exception:
        current_app.logger.warning("Trash classroom membership notification failed", exc_info=True)


def _extended_delete_interceptor():
    if request.method != "POST" or not session.get("user_id"):
        return None
    endpoint = request.endpoint or ""
    role = session.get("role")
    if role not in {"student", "supervisor"}:
        return None

    if endpoint in {"student.delete_log", "supervisor.delete_task"}:
        return None

    actor_id = _active_actor(role)
    target_endpoints = {
        "classwork.remove_work",
        "classroom.remove_student",
        "classroom.leave_class",
        "student.delete_document",
        "student.delete_task_submission",
        "daily_logbook.delete_photo",
        "notifications.delete_selected_notifications",
        "notifications.delete_by_date",
    }
    if endpoint not in target_endpoints:
        return None
    if actor_id is None:
        return "Forbidden", 403

    view_args = request.view_args or {}
    if endpoint == "classwork.remove_work" and role == "supervisor":
        class_id = view_args.get("class_id")
        assignment_id = view_args.get("assignment_id")
        if class_id is None or assignment_id is None:
            return None
        ok, message = _move_work(actor_id, int(class_id), int(assignment_id))
        flash(message, "success" if ok else "warning")
        return redirect(url_for("classwork.manage_classwork", class_id=int(class_id)))

    if endpoint == "classroom.remove_student" and role == "supervisor":
        class_id = view_args.get("class_id")
        student_id = view_args.get("student_id")
        if class_id is None or student_id is None:
            return None
        ok, message, payload = _move_membership(actor_id, "supervisor", int(class_id), int(student_id))
        if ok:
            _notify_membership_change(payload, "supervisor")
            flash("Student removed from class and moved to Trash.", "success")
        else:
            flash(message, "warning")
        return redirect(url_for("classroom.supervisor_class", class_id=int(class_id)))

    if endpoint == "classroom.leave_class" and role == "student":
        class_id = view_args.get("class_id")
        if class_id is None:
            return None
        ok, message, payload = _move_membership(actor_id, "student", int(class_id), actor_id)
        if ok:
            _notify_membership_change(payload, "student")
            class_name = (payload or {}).get("classroom_name") or "the Intern Classroom"
            flash(f"You left {class_name}. The membership can be restored from Trash for 30 days.", "success")
        else:
            flash(message, "warning")
        return redirect(url_for("classroom.student_classes"))

    if endpoint == "student.delete_document" and role == "student":
        document_id = view_args.get("document_id")
        if document_id is None:
            return None
        ok, message = _move_document(actor_id, int(document_id))
        flash(message, "success" if ok else "warning")
        return redirect(url_for("student.documents"))

    if endpoint == "student.delete_task_submission" and role == "student":
        submission_id = view_args.get("submission_id")
        if submission_id is None:
            return None
        ok, message, task_id = _move_task_submission(actor_id, int(submission_id))
        flash(message, "success" if ok else "warning")
        return redirect(f"/student/task/{task_id}" if task_id else url_for("student.tasks"))

    if endpoint == "daily_logbook.delete_photo" and role == "student":
        photo_id = view_args.get("photo_id")
        if photo_id is None:
            return None
        ok, message, photo = _move_logbook_photo(actor_id, int(photo_id))
        flash(message, "success" if ok else "warning")
        if photo and photo.get("attendance_id"):
            return redirect(url_for("student.view_session", attendance_id=int(photo["attendance_id"])))
        return redirect(url_for("student.logbook"))

    if endpoint == "notifications.delete_selected_notifications":
        requested_page = request.form.get("page", 1, type=int) or 1
        raw_ids = request.form.getlist("notification_ids")
        normalized = []
        seen = set()
        for raw_id in raw_ids:
            try:
                notification_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if notification_id > 0 and notification_id not in seen:
                normalized.append(notification_id)
                seen.add(notification_id)
        if not normalized:
            flash("Select at least one notification to delete.", "error")
        elif len(normalized) > 15:
            flash("You can delete up to 15 selected notifications at a time.", "error")
        else:
            moved = _move_notifications(actor_id, normalized)
            if moved:
                flash(f"Moved {moved} selected notification{'s' if moved != 1 else ''} to Trash.", "success")
            else:
                flash("No selected notifications were moved to Trash.", "info")
        return redirect(url_for("notifications.notification_list", page=max(1, requested_page)))

    if endpoint == "notifications.delete_by_date":
        raw_date = (request.form.get("delete_date") or "").strip()
        if not raw_date:
            flash("Choose a date before deleting notifications.", "error")
            return redirect(url_for("notifications.notification_list"))
        try:
            target_date = date.fromisoformat(raw_date)
        except ValueError:
            flash("The selected notification date is invalid.", "error")
            return redirect(url_for("notifications.notification_list"))
        if target_date > date.today():
            flash("Choose today or an earlier date.", "error")
            return redirect(url_for("notifications.notification_list"))
        ids = _notification_ids_for_date(actor_id, target_date)
        moved = _move_notifications(actor_id, ids)
        if moved:
            flash(
                f"Moved {moved} notification{'s' if moved != 1 else ''} from {target_date.strftime('%B %d, %Y')} to Trash.",
                "success",
            )
        else:
            flash(f"No notifications were found for {target_date.strftime('%B %d, %Y')}.", "info")
        return redirect(url_for("notifications.notification_list"))

    return None


def install_role_trash_extension():
    if getattr(_trash, "_role_trash_extension_installed", False):
        return

    _trash._move_student_log_to_role_trash = _move_student_log_to_role_trash
    _trash._move_supervisor_task_to_role_trash = _move_supervisor_task_to_role_trash
    _trash._list_role_trash = _list_role_trash
    _trash._restore_role_trash_item = _restore_role_trash_item
    _trash._purge_role_trash_row = _purge_role_trash_row
    _trash.render_template = _role_trash_render
    _bp.before_app_request(_extended_delete_interceptor)
    _trash._role_trash_extension_installed = True


install_role_trash_extension()
