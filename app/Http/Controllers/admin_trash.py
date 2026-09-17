import json
import os
import re
from datetime import datetime, timedelta
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, flash, url_for
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection, using_postgres

admin_trash = Blueprint("admin_trash", __name__)

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_DELETE_TARGETS = frozenset({
    ("classroom_students", "student_id"),
    ("student_assignments", "student_id"),
    ("notifications", "user_id"),
    ("attendance", "student_id"),
    ("logs", "student_id"),
    ("documents", "student_id"),
    ("tasks", "student_id"),
    ("internships", "student_id"),
    ("feedback", "student_id"),
    ("classwork_scores", "student_id"),
    ("classwork_submissions", "student_id"),
    ("student_profiles", "user_id"),
    ("users", "id"),
    ("admin_user_trash", "user_id"),
    ("role_trash_items", "owner_user_id"),
})

_ROLE_TRASH_RETENTION_DAYS = 30


def ensure_trash_schema(conn):
    if using_postgres():
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_user_trash (id SERIAL PRIMARY KEY,user_id INTEGER UNIQUE,username TEXT,email TEXT,role TEXT,deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_user_trash (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE,username TEXT,email TEXT,role TEXT,deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    try:
        conn.execute("UPDATE users SET role='deleted' WHERE username LIKE 'deleted_%' AND role != 'deleted'")
    except Exception:
        pass
    conn.commit()


def ensure_role_trash_schema(conn):
    if using_postgres():
        conn.execute("""
            CREATE TABLE IF NOT EXISTS role_trash_items (
                id SERIAL PRIMARY KEY,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                owner_role TEXT NOT NULL,
                item_type TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                previous_state TEXT,
                payload TEXT,
                deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS role_trash_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                owner_role TEXT NOT NULL,
                item_type TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                previous_state TEXT,
                payload TEXT,
                deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_role_trash_owner_item
        ON role_trash_items(owner_user_id, owner_role, item_type, item_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_role_trash_expiry
        ON role_trash_items(owner_user_id, owner_role, expires_at)
    """)
    conn.commit()


def _safe_delete(conn, table, column, user_id):
    """Delete a dependent row only when its SQL identifiers are explicitly allowed."""
    if (
        (table, column) not in _SAFE_DELETE_TARGETS
        or not _SQL_IDENTIFIER_RE.fullmatch(table or "")
        or not _SQL_IDENTIFIER_RE.fullmatch(column or "")
    ):
        return False

    conn.execute("SAVEPOINT nexora_trash_delete")
    try:
        conn.execute(f"DELETE FROM {table} WHERE {column}=?", (user_id,))
        conn.execute("RELEASE SAVEPOINT nexora_trash_delete")
        return True
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT nexora_trash_delete")
            conn.execute("RELEASE SAVEPOINT nexora_trash_delete")
        except Exception:
            pass
        return False


def purge_expired(conn):
    cutoff = datetime.now() - timedelta(days=30)
    rows = conn.execute("SELECT user_id FROM admin_user_trash WHERE deleted_at < ?", (cutoff,)).fetchall()
    for row in rows:
        uid = row[0]
        deleted = _safe_delete(conn, "users", "id", uid) if conn.execute("SELECT 1 FROM users WHERE id=? AND status='inactive'", (uid,)).fetchone() else True
        if deleted:
            _safe_delete(conn, "admin_user_trash", "user_id", uid)
    conn.commit()


def seed_existing(conn):
    inactive = conn.execute("SELECT id,username,email,role FROM users WHERE status='inactive'").fetchall()
    for u in inactive:
        uid = u[0]
        exists = conn.execute("SELECT 1 FROM admin_user_trash WHERE user_id=?", (uid,)).fetchone()
        if not exists:
            conn.execute("INSERT INTO admin_user_trash (user_id,username,email,role) VALUES (?,?,?,?)", (uid, u[1], u[2], u[3]))
    conn.commit()


def _parse_dashboard_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _format_dashboard_timestamp(value):
    parsed = _parse_dashboard_timestamp(value)
    if not parsed:
        return "Timestamp unavailable"
    return parsed.strftime("%b %d, %Y • %I:%M %p").lstrip("0")


def _role_trash_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _role_trash_label(value):
    parsed = _role_trash_datetime(value)
    return parsed.strftime("%b %d, %Y") if parsed else "Unknown"


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _upsert_role_trash_item(conn, owner_user_id, owner_role, item_type, item_id, previous_state=None, payload=None):
    now = datetime.now()
    expires_at = now + timedelta(days=_ROLE_TRASH_RETENTION_DAYS)
    existing = conn.execute(
        """
        SELECT id
        FROM role_trash_items
        WHERE owner_user_id = ? AND owner_role = ? AND item_type = ? AND item_id = ?
        LIMIT 1
        """,
        (owner_user_id, owner_role, item_type, item_id),
    ).fetchone()
    payload_text = json.dumps(payload, default=_json_default) if payload is not None else None
    if existing:
        conn.execute(
            """
            UPDATE role_trash_items
            SET previous_state = ?, payload = ?, deleted_at = ?, expires_at = ?
            WHERE id = ?
            """,
            (previous_state, payload_text, now, expires_at, existing[0]),
        )
        return int(existing[0])
    conn.execute(
        """
        INSERT INTO role_trash_items (
            owner_user_id, owner_role, item_type, item_id,
            previous_state, payload, deleted_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (owner_user_id, owner_role, item_type, item_id, previous_state, payload_text, now, expires_at),
    )
    created = conn.execute(
        """
        SELECT id
        FROM role_trash_items
        WHERE owner_user_id = ? AND owner_role = ? AND item_type = ? AND item_id = ?
        LIMIT 1
        """,
        (owner_user_id, owner_role, item_type, item_id),
    ).fetchone()
    return int(created[0]) if created else 0


def _task_snapshot(conn, task_id, supervisor_id):
    task = conn.execute(
        """
        SELECT id, student_id, supervisor_id, task_title, task_description,
               assigned_at, deadline, requires_submission, allow_late_submission, status
        FROM tasks
        WHERE id = ? AND supervisor_id = ?
        LIMIT 1
        """,
        (task_id, supervisor_id),
    ).fetchone()
    if not task:
        return None
    task_keys = (
        "id", "student_id", "supervisor_id", "task_title", "task_description",
        "assigned_at", "deadline", "requires_submission", "allow_late_submission", "status",
    )
    task_data = {key: task[index] for index, key in enumerate(task_keys)}
    submissions = conn.execute(
        """
        SELECT id, task_id, filename, filepath, submitted_at, remarks
        FROM task_submissions
        WHERE task_id = ?
        ORDER BY id
        """,
        (task_id,),
    ).fetchall()
    submission_keys = ("id", "task_id", "filename", "filepath", "submitted_at", "remarks")
    submission_data = [
        {key: row[index] for index, key in enumerate(submission_keys)}
        for row in submissions
    ]
    return {"task": task_data, "submissions": submission_data}


def _move_student_log_to_role_trash(student_id, log_id):
    conn = get_db_connection()
    try:
        ensure_role_trash_schema(conn)
        row = conn.execute(
            """
            SELECT l.id, COALESCE(l.entry_type, 'activity'), l.attendance_id, a.status
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            WHERE l.id = ? AND l.student_id = ?
            LIMIT 1
            """,
            (log_id, student_id),
        ).fetchone()
        if not row:
            return False, "Logbook entry not found."
        entry_type = str(row[1] or "activity")
        if entry_type.startswith("trash_"):
            return True, "Daily OJT entry is already in Trash."
        if row[3] != "Open":
            return False, "Previous OJT days are read-only and cannot be moved to Trash."
        _upsert_role_trash_item(
            conn,
            student_id,
            "student",
            "logbook",
            int(log_id),
            previous_state=entry_type,
        )
        conn.execute(
            "UPDATE logs SET entry_type = ? WHERE id = ? AND student_id = ?",
            (f"trash_{entry_type}", log_id, student_id),
        )
        conn.commit()
        return True, "Daily OJT entry moved to Trash."
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _move_supervisor_task_to_role_trash(supervisor_id, task_id):
    conn = get_db_connection()
    try:
        ensure_role_trash_schema(conn)
        snapshot = _task_snapshot(conn, task_id, supervisor_id)
        if not snapshot:
            return False, "Task not found or access denied.", None
        task = snapshot["task"]
        _upsert_role_trash_item(
            conn,
            supervisor_id,
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
        conn.rollback()
        raise
    finally:
        conn.close()


def _safe_remove_upload(filepath):
    if not filepath:
        return
    upload_base = current_app.config.get("UPLOAD_FOLDER", "")
    if not upload_base:
        return
    try:
        base = os.path.realpath(upload_base)
        target = os.path.realpath(str(filepath))
        if os.path.commonpath([base, target]) != base:
            return
        if os.path.isfile(target):
            os.remove(target)
    except (OSError, ValueError, TypeError):
        pass


def _safe_remove_logbook_photo(relative_path):
    if not relative_path:
        return
    try:
        from app.Services.logbook_photo_service import PHOTO_ROOT
        root = PHOTO_ROOT.resolve()
        target = (root / str(relative_path)).resolve()
        if target != root and root not in target.parents:
            return
        if target.is_file():
            target.unlink()
    except (OSError, ValueError, TypeError):
        pass


def _purge_role_trash_row(conn, row):
    trash_id = int(row[0])
    owner_user_id = int(row[1])
    owner_role = str(row[2])
    item_type = str(row[3])
    item_id = int(row[4])
    payload_text = row[6]
    cleanup = []

    if owner_role == "student" and item_type == "logbook":
        try:
            photo_rows = conn.execute(
                "SELECT relative_path FROM logbook_photos WHERE log_id = ?",
                (item_id,),
            ).fetchall()
            cleanup.extend(("photo", photo[0]) for photo in photo_rows if photo[0])
        except Exception:
            pass
        conn.execute("DELETE FROM logs WHERE id = ? AND student_id = ?", (item_id, owner_user_id))
    elif owner_role == "supervisor" and item_type == "task":
        try:
            payload = json.loads(payload_text or "{}")
        except (TypeError, ValueError):
            payload = {}
        for submission in payload.get("submissions", []) or []:
            filepath = submission.get("filepath")
            if filepath:
                cleanup.append(("upload", filepath))

    conn.execute("DELETE FROM role_trash_items WHERE id = ?", (trash_id,))
    return cleanup


def _purge_expired_role_trash(conn, owner_user_id, owner_role):
    now = datetime.now()
    rows = conn.execute(
        """
        SELECT id, owner_user_id, owner_role, item_type, item_id, previous_state, payload, deleted_at, expires_at
        FROM role_trash_items
        WHERE owner_user_id = ? AND owner_role = ? AND expires_at <= ?
        ORDER BY expires_at ASC
        """,
        (owner_user_id, owner_role, now),
    ).fetchall()
    cleanup = []
    for row in rows:
        cleanup.extend(_purge_role_trash_row(conn, row))
    if rows:
        conn.commit()
    for kind, path in cleanup:
        if kind == "photo":
            _safe_remove_logbook_photo(path)
        else:
            _safe_remove_upload(path)


def _student_name(conn, student_id):
    row = conn.execute(
        """
        SELECT u.username,
               COALESCE(sp.first_name, ''),
               COALESCE(sp.middle_name, ''),
               COALESCE(sp.last_name, '')
        FROM users u
        LEFT JOIN student_profiles sp ON sp.user_id = u.id
        WHERE u.id = ?
        LIMIT 1
        """,
        (student_id,),
    ).fetchone()
    if not row:
        return "Student"
    parts = [str(row[index] or "").strip() for index in (1, 2, 3)]
    return " ".join(part for part in parts if part) or str(row[0] or "Student")


def _list_role_trash(owner_user_id, owner_role):
    conn = get_db_connection()
    try:
        ensure_role_trash_schema(conn)
        _purge_expired_role_trash(conn, owner_user_id, owner_role)
        rows = conn.execute(
            """
            SELECT id, owner_user_id, owner_role, item_type, item_id, previous_state, payload, deleted_at, expires_at
            FROM role_trash_items
            WHERE owner_user_id = ? AND owner_role = ?
            ORDER BY deleted_at DESC, id DESC
            """,
            (owner_user_id, owner_role),
        ).fetchall()
        items = []
        now = datetime.now()
        for row in rows:
            trash_id = int(row[0])
            item_type = str(row[3])
            deleted_at = _role_trash_datetime(row[7])
            expires_at = _role_trash_datetime(row[8])
            days_left = max(0, (expires_at.date() - now.date()).days) if expires_at else 0

            if owner_role == "student" and item_type == "logbook":
                log = conn.execute(
                    """
                    SELECT l.content, l.created_at, a.clock_in,
                           COALESCE(c.name, 'Legacy attendance')
                    FROM logs l
                    JOIN attendance a ON a.id = l.attendance_id
                    LEFT JOIN classrooms c ON c.id = a.classroom_id
                    WHERE l.id = ? AND l.student_id = ?
                    LIMIT 1
                    """,
                    (int(row[4]), owner_user_id),
                ).fetchone()
                if not log:
                    conn.execute("DELETE FROM role_trash_items WHERE id = ?", (trash_id,))
                    continue
                content = str(log[0] or "Daily OJT entry").strip()
                snippet = content if len(content) <= 115 else f"{content[:112]}..."
                items.append({
                    "id": trash_id,
                    "item_type": "logbook",
                    "type_label": "Logbook",
                    "title": "Daily OJT Logbook Entry",
                    "subtitle": f"{str(log[3] or 'Legacy attendance')} · {snippet}",
                    "deleted_label": _role_trash_label(deleted_at),
                    "expires_label": _role_trash_label(expires_at),
                    "days_left": days_left,
                    "restore_url": url_for("admin_trash.student_trash_restore", trash_id=trash_id),
                    "permanent_url": url_for("admin_trash.student_trash_permanent", trash_id=trash_id),
                })
            elif owner_role == "supervisor" and item_type == "task":
                try:
                    payload = json.loads(row[6] or "{}")
                except (TypeError, ValueError):
                    payload = {}
                task = payload.get("task") or {}
                student_name = _student_name(conn, task.get("student_id")) if task.get("student_id") else "Student"
                status = str(task.get("status") or row[5] or "Pending")
                items.append({
                    "id": trash_id,
                    "item_type": "task",
                    "type_label": "Task",
                    "title": str(task.get("task_title") or "Assigned Task"),
                    "subtitle": f"{student_name} · Previous status: {status}",
                    "deleted_label": _role_trash_label(deleted_at),
                    "expires_label": _role_trash_label(expires_at),
                    "days_left": days_left,
                    "restore_url": url_for("admin_trash.supervisor_trash_restore", trash_id=trash_id),
                    "permanent_url": url_for("admin_trash.supervisor_trash_permanent", trash_id=trash_id),
                })
        conn.commit()
        expiring_soon = sum(1 for item in items if item["days_left"] <= 7)
        return items, expiring_soon
    finally:
        conn.close()


def _restore_role_trash_item(owner_user_id, owner_role, trash_id):
    conn = get_db_connection()
    try:
        ensure_role_trash_schema(conn)
        row = conn.execute(
            """
            SELECT id, owner_user_id, owner_role, item_type, item_id, previous_state, payload, deleted_at, expires_at
            FROM role_trash_items
            WHERE id = ? AND owner_user_id = ? AND owner_role = ?
            LIMIT 1
            """,
            (trash_id, owner_user_id, owner_role),
        ).fetchone()
        if not row:
            return False, "Trash item not found."

        item_type = str(row[3])
        item_id = int(row[4])
        if owner_role == "student" and item_type == "logbook":
            log = conn.execute(
                "SELECT attendance_id FROM logs WHERE id = ? AND student_id = ? LIMIT 1",
                (item_id, owner_user_id),
            ).fetchone()
            if not log:
                conn.execute("DELETE FROM role_trash_items WHERE id = ?", (trash_id,))
                conn.commit()
                return False, "That Logbook entry no longer exists."
            previous_state = str(row[5] or "daily")
            if previous_state == "daily":
                conflict = conn.execute(
                    """
                    SELECT 1
                    FROM logs
                    WHERE attendance_id = ? AND student_id = ? AND entry_type = 'daily' AND id != ?
                    LIMIT 1
                    """,
                    (log[0], owner_user_id, item_id),
                ).fetchone()
                if conflict:
                    return False, "A replacement Daily OJT entry already exists for that attendance day."
            conn.execute(
                "UPDATE logs SET entry_type = ? WHERE id = ? AND student_id = ?",
                (previous_state, item_id, owner_user_id),
            )
        elif owner_role == "supervisor" and item_type == "task":
            try:
                payload = json.loads(row[6] or "{}")
            except (TypeError, ValueError):
                payload = {}
            task = payload.get("task") or {}
            if not task or int(task.get("supervisor_id") or 0) != int(owner_user_id):
                return False, "Task recovery data is incomplete."
            existing = conn.execute("SELECT 1 FROM tasks WHERE id = ? LIMIT 1", (item_id,)).fetchone()
            if existing:
                return False, "That task ID is already active and cannot be restored."
            conn.execute(
                """
                INSERT INTO tasks (
                    id, student_id, supervisor_id, task_title, task_description,
                    assigned_at, deadline, requires_submission, allow_late_submission, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(task.get("id") or item_id),
                    int(task["student_id"]),
                    int(task["supervisor_id"]),
                    task.get("task_title") or "Recovered Task",
                    task.get("task_description"),
                    task.get("assigned_at"),
                    task.get("deadline"),
                    int(task.get("requires_submission") or 0),
                    int(task.get("allow_late_submission") or 0),
                    task.get("status") or row[5] or "Pending",
                ),
            )
            for submission in payload.get("submissions", []) or []:
                conn.execute(
                    """
                    INSERT INTO task_submissions (id, task_id, filename, filepath, submitted_at, remarks)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(submission["id"]),
                        int(task.get("id") or item_id),
                        submission.get("filename") or "Recovered submission",
                        submission.get("filepath") or "",
                        submission.get("submitted_at"),
                        submission.get("remarks"),
                    ),
                )
        else:
            return False, "This Trash item is not valid for your account."

        conn.execute("DELETE FROM role_trash_items WHERE id = ?", (trash_id,))
        conn.commit()
        return True, "Item restored successfully."
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _permanent_delete_role_trash_item(owner_user_id, owner_role, trash_id):
    conn = get_db_connection()
    cleanup = []
    try:
        ensure_role_trash_schema(conn)
        row = conn.execute(
            """
            SELECT id, owner_user_id, owner_role, item_type, item_id, previous_state, payload, deleted_at, expires_at
            FROM role_trash_items
            WHERE id = ? AND owner_user_id = ? AND owner_role = ?
            LIMIT 1
            """,
            (trash_id, owner_user_id, owner_role),
        ).fetchone()
        if not row:
            return False, "Trash item not found."
        cleanup = _purge_role_trash_row(conn, row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for kind, path in cleanup:
        if kind == "photo":
            _safe_remove_logbook_photo(path)
        else:
            _safe_remove_upload(path)
    return True, "Item permanently deleted."


@admin_trash.before_app_request
def intercept_role_owned_deletes():
    if request.method != "POST" or not session.get("user_id"):
        return None

    if request.endpoint == "student.delete_log" and session.get("role") == "student":
        log_id = (request.view_args or {}).get("log_id")
        if log_id is None:
            return None
        ok, message = _move_student_log_to_role_trash(int(session["user_id"]), int(log_id))
        flash(message, "success" if ok else "warning")
        return redirect(url_for("student.logbook"))

    if request.endpoint == "supervisor.delete_task" and session.get("role") == "supervisor":
        task_id = (request.view_args or {}).get("task_id")
        if task_id is None:
            return None
        ok, message, student_id = _move_supervisor_task_to_role_trash(int(session["user_id"]), int(task_id))
        flash(message, "success" if ok else "warning")
        if student_id:
            return redirect(f"/supervisor/student/{student_id}")
        return redirect(url_for("supervisor.view_interns"))

    return None


@admin_trash.app_context_processor
def inject_admin_dashboard_actionable_metrics():
    def get_admin_dashboard_actionable_metrics():
        default_metrics = {
            "unenrolled_students": 0,
            "trash_expiring_soon": 0,
            "recent_activities": [],
            "system_status": {
                "database_status": "Not verified",
                "database_engine": "Not verified",
                "email_status": "Not configured",
                "email_configured": False,
            },
        }
        if session.get("role") != "admin":
            return default_metrics

        conn = get_db_connection()
        try:
            # Match the Student portal's authoritative definition of an active
            # Internship Classroom enrollment instead of legacy assignments.
            unenrolled_row = conn.execute(
                """
                SELECT COUNT(*)
                FROM users u
                WHERE u.role = 'student'
                  AND COALESCE(u.status, 'active') = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM classroom_students cs
                      JOIN classrooms c ON c.id = cs.classroom_id
                      WHERE cs.student_id = u.id
                        AND COALESCE(c.archived, 0) = 0
                        AND COALESCE(c.classroom_type, 'classroom') = 'internship'
                  )
                """
            ).fetchone()

            # Trash entries are retained for 30 days. Keep this Dashboard read
            # side-effect free: if Trash has not been initialized, show 0.
            trash_expiring_soon = 0
            now = datetime.now()
            trash_window_start = now - timedelta(days=30)
            trash_window_end = now - timedelta(days=23)
            try:
                trash_row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM admin_user_trash
                    WHERE deleted_at >= ?
                      AND deleted_at <= ?
                    """,
                    (trash_window_start, trash_window_end),
                ).fetchone()
                trash_expiring_soon = int((trash_row[0] if trash_row else 0) or 0)
            except Exception:
                trash_expiring_soon = 0

            recent_activities = []
            try:
                classroom_rows = conn.execute(
                    """
                    SELECT c.name, c.classroom_type, c.created_at,
                           u.username AS supervisor_name
                    FROM classrooms c
                    JOIN users u ON u.id = c.supervisor_id
                    WHERE c.created_at IS NOT NULL
                    ORDER BY c.created_at DESC
                    LIMIT 8
                    """
                ).fetchall()
                for row in classroom_rows:
                    event_at = _parse_dashboard_timestamp(row[2])
                    if not event_at:
                        continue
                    classroom_label = "Intern Classroom" if row[1] == "internship" else "Classroom"
                    recent_activities.append({
                        "sort_at": event_at,
                        "title": f"{classroom_label} '{row[0]}' created",
                        "context": f"Created by {row[3]}",
                        "timestamp": _format_dashboard_timestamp(row[2]),
                        "tone": "red",
                        "icon": "▣",
                    })

                enrollment_rows = conn.execute(
                    """
                    SELECT s.username, c.name, cs.joined_at
                    FROM classroom_students cs
                    JOIN classrooms c ON c.id = cs.classroom_id
                    JOIN users s ON s.id = cs.student_id
                    WHERE c.classroom_type = 'internship'
                      AND cs.joined_at IS NOT NULL
                    ORDER BY cs.joined_at DESC
                    LIMIT 8
                    """
                ).fetchall()
                for row in enrollment_rows:
                    event_at = _parse_dashboard_timestamp(row[2])
                    if not event_at:
                        continue
                    recent_activities.append({
                        "sort_at": event_at,
                        "title": f"{row[0]} joined an Intern Classroom",
                        "context": row[1],
                        "timestamp": _format_dashboard_timestamp(row[2]),
                        "tone": "orange",
                        "icon": "♟",
                    })

                feedback_rows = conn.execute(
                    """
                    SELECT student.username, supervisor.username, f.created_at
                    FROM feedback f
                    JOIN users student ON student.id = f.student_id
                    JOIN users supervisor ON supervisor.id = f.supervisor_id
                    WHERE f.created_at IS NOT NULL
                    ORDER BY f.created_at DESC
                    LIMIT 8
                    """
                ).fetchall()
                for row in feedback_rows:
                    event_at = _parse_dashboard_timestamp(row[2])
                    if not event_at:
                        continue
                    recent_activities.append({
                        "sort_at": event_at,
                        "title": f"Feedback submitted for {row[0]}",
                        "context": f"Submitted by {row[1]}",
                        "timestamp": _format_dashboard_timestamp(row[2]),
                        "tone": "purple",
                        "icon": "◌",
                    })
            except Exception as exc:
                print("admin dashboard recent activity failed:", exc)

            recent_activities.sort(
                key=lambda activity: activity["sort_at"],
                reverse=True,
            )
            recent_activities = recent_activities[:6]
            for activity in recent_activities:
                activity.pop("sort_at", None)

            email_configured = bool(
                os.environ.get("BREVO_API_KEY", "").strip()
                and os.environ.get("BREVO_SENDER_EMAIL", "").strip()
            )

            return {
                "unenrolled_students": int((unenrolled_row[0] if unenrolled_row else 0) or 0),
                "trash_expiring_soon": trash_expiring_soon,
                "recent_activities": recent_activities,
                "system_status": {
                    "database_status": "Available",
                    "database_engine": "PostgreSQL" if using_postgres() else "SQLite",
                    "email_status": "Configured" if email_configured else "Not configured",
                    "email_configured": email_configured,
                },
            }
        except Exception as exc:
            print("admin dashboard actionable metrics failed:", exc)
            return default_metrics
        finally:
            conn.close()

    return {"get_admin_dashboard_actionable_metrics": get_admin_dashboard_actionable_metrics}


@admin_trash.route("/admin/trash")
@role_required("admin")
def trash():
    conn = get_db_connection()
    try:
        ensure_trash_schema(conn)
        seed_existing(conn)
        purge_expired(conn)
        rows = conn.execute("SELECT id,user_id,username,email,role,deleted_at FROM admin_user_trash ORDER BY deleted_at DESC").fetchall()
    finally:
        conn.close()
    return render_template("admin/trash.html", trash_items=rows, active_page="trash")


@admin_trash.route("/admin/trash/data")
@role_required("admin")
def trash_data():
    conn = get_db_connection()
    try:
        ensure_trash_schema(conn)
        seed_existing(conn)
        purge_expired(conn)
        rows = conn.execute("SELECT user_id FROM admin_user_trash ORDER BY deleted_at DESC").fetchall()
        return jsonify({"ids": [int(r[0]) for r in rows]})
    finally:
        conn.close()


@admin_trash.route("/admin/trash/delete/<int:user_id>", methods=["POST"])
@role_required("admin")
def move_to_trash(user_id):
    conn = get_db_connection()
    try:
        ensure_trash_schema(conn)
        user = conn.execute("SELECT id,username,email,role,status FROM users WHERE id=? AND role!='admin'", (user_id,)).fetchone()
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404
        conn.execute("""INSERT INTO admin_user_trash (user_id,username,email,role,deleted_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET deleted_at=CURRENT_TIMESTAMP,username=excluded.username,email=excluded.email,role=excluded.role""", (user[0], user[1], user[2], user[3]))
        conn.execute("UPDATE users SET status='inactive' WHERE id=? AND role!='admin'", (user_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as exc:
        conn.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        conn.close()


@admin_trash.route("/admin/trash/restore/<int:user_id>", methods=["POST"])
@role_required("admin")
def restore(user_id):
    conn = get_db_connection()
    try:
        ensure_trash_schema(conn)
        row = conn.execute("SELECT role FROM admin_user_trash WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return redirect("/admin/trash")
        conn.execute("UPDATE users SET status='active' WHERE id=? AND role!='admin'", (user_id,))
        conn.execute("DELETE FROM admin_user_trash WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    flash("User restored successfully.", "success")
    return redirect("/admin/trash")


@admin_trash.route("/admin/trash/permanent/<int:user_id>", methods=["POST"])
@role_required("admin")
def permanent_delete(user_id):
    conn = get_db_connection()
    try:
        ensure_trash_schema(conn)
        user = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if user and user[0] != "admin":
            dependencies = (
                ("classroom_students", "student_id"),
                ("student_assignments", "student_id"),
                ("notifications", "user_id"),
                ("attendance", "student_id"),
                ("logs", "student_id"),
                ("documents", "student_id"),
                ("tasks", "student_id"),
                ("internships", "student_id"),
                ("feedback", "student_id"),
                ("classwork_scores", "student_id"),
                ("classwork_submissions", "student_id"),
                ("role_trash_items", "owner_user_id"),
            )
            for table, column in dependencies:
                _safe_delete(conn, table, column, user_id)
            _safe_delete(conn, "student_profiles", "user_id", user_id)

            deleted_user = _safe_delete(conn, "users", "id", user_id)
            if not deleted_user:
                # FK-linked records not covered above should not cause a 500.
                conn.execute("SAVEPOINT nexora_trash_anonymize")
                try:
                    conn.execute("UPDATE users SET username=?,email=NULL,status='inactive',role='deleted' WHERE id=?", (f"deleted_{user_id}", user_id))
                    conn.execute("RELEASE SAVEPOINT nexora_trash_anonymize")
                except Exception:
                    try:
                        conn.execute("ROLLBACK TO SAVEPOINT nexora_trash_anonymize")
                        conn.execute("RELEASE SAVEPOINT nexora_trash_anonymize")
                    except Exception:
                        pass
            _safe_delete(conn, "admin_user_trash", "user_id", user_id)
            conn.commit()
    finally:
        conn.close()
    flash("User permanently removed from the account directory.", "success")
    return redirect("/admin/trash")


@admin_trash.route("/student/trash")
@role_required("student")
def student_trash():
    items, expiring_soon = _list_role_trash(int(session["user_id"]), "student")
    return render_template(
        "shared/role_trash.html",
        trash_role="student",
        trash_items=items,
        expiring_soon=expiring_soon,
        trash_item_label="Logbook Entries",
        trash_description="Deleted Daily OJT Logbook entries remain recoverable for 30 days.",
        trash_empty_copy="Daily OJT entries you remove will appear here for up to 30 days.",
        active_page="trash",
    )


@admin_trash.route("/student/trash/<int:trash_id>/restore", methods=["POST"])
@role_required("student")
def student_trash_restore(trash_id):
    ok, message = _restore_role_trash_item(int(session["user_id"]), "student", trash_id)
    flash(message, "success" if ok else "warning")
    return redirect(url_for("admin_trash.student_trash"))


@admin_trash.route("/student/trash/<int:trash_id>/permanent", methods=["POST"])
@role_required("student")
def student_trash_permanent(trash_id):
    ok, message = _permanent_delete_role_trash_item(int(session["user_id"]), "student", trash_id)
    flash(message, "success" if ok else "warning")
    return redirect(url_for("admin_trash.student_trash"))


@admin_trash.route("/supervisor/trash")
@role_required("supervisor")
def supervisor_trash():
    items, expiring_soon = _list_role_trash(int(session["user_id"]), "supervisor")
    return render_template(
        "shared/role_trash.html",
        trash_role="supervisor",
        trash_items=items,
        expiring_soon=expiring_soon,
        trash_item_label="Assigned Tasks",
        trash_description="Deleted assigned Tasks remain recoverable for 30 days.",
        trash_empty_copy="Tasks you remove from assigned interns will appear here for up to 30 days.",
        active_page="trash",
    )


@admin_trash.route("/supervisor/trash/<int:trash_id>/restore", methods=["POST"])
@role_required("supervisor")
def supervisor_trash_restore(trash_id):
    ok, message = _restore_role_trash_item(int(session["user_id"]), "supervisor", trash_id)
    flash(message, "success" if ok else "warning")
    return redirect(url_for("admin_trash.supervisor_trash"))


@admin_trash.route("/supervisor/trash/<int:trash_id>/permanent", methods=["POST"])
@role_required("supervisor")
def supervisor_trash_permanent(trash_id):
    ok, message = _permanent_delete_role_trash_item(int(session["user_id"]), "supervisor", trash_id)
    flash(message, "success" if ok else "warning")
    return redirect(url_for("admin_trash.supervisor_trash"))
