import os
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, redirect, render_template, session, flash
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection, using_postgres

admin_trash = Blueprint("admin_trash", __name__)


def ensure_trash_schema(conn):
    if using_postgres():
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_user_trash (id SERIAL PRIMARY KEY,user_id INTEGER UNIQUE,username TEXT,email TEXT,role TEXT,deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_user_trash (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE,username TEXT,email TEXT,role TEXT,deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()


def _safe_delete(conn, table, column, user_id):
    """Delete a dependent row without poisoning the surrounding transaction."""
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
            )
            for table, column in dependencies:
                _safe_delete(conn, table, column, user_id)
            _safe_delete(conn, "student_profiles", "user_id", user_id)

            deleted_user = _safe_delete(conn, "users", "id", user_id)
            if not deleted_user:
                # FK-linked records not covered above should not cause a 500.
                conn.execute("SAVEPOINT nexora_trash_anonymize")
                try:
                    conn.execute("UPDATE users SET username=?,email=NULL,status='inactive' WHERE id=?", (f"deleted_{user_id}", user_id))
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
