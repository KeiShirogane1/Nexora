from functools import wraps
from flask import session, redirect
from app.Models.db import get_db_connection


def _dashboard_for_role(role):
    return {
        "student": "/student/dashboard",
        "supervisor": "/supervisor/dashboard",
        "admin": "/admin/dashboard",
    }.get(role, "/login")


def role_required(role):

    def wrapper(func):
        @wraps(func)
        def inner(*args, **kwargs):

            if "user_id" not in session:
                return redirect("/login")

            # Never trust a stale role stored in the browser session. Re-check
            # the user's current role in the database so a supervisor cannot
            # accidentally remain in the student UI (and vice versa).
            conn = get_db_connection()
            try:
                row = conn.execute(
                    "SELECT role, status FROM users WHERE id = ?",
                    (session.get("user_id"),),
                ).fetchone()
            finally:
                conn.close()

            if row is None:
                session.clear()
                return redirect("/login")

            try:
                actual_role = row["role"]
                status = row["status"]
            except Exception:
                actual_role = row[0]
                status = row[1] if len(row) > 1 else None

            if status == "inactive":
                session.clear()
                return "Account deactivated — contact administrator.", 403

            if actual_role != role:
                # Repair stale session role immediately and send the user to
                # the dashboard belonging to the role stored in the database.
                session["role"] = actual_role
                return redirect(_dashboard_for_role(actual_role))

            session["role"] = actual_role
            return func(*args, **kwargs)

        return inner

    return wrapper


def login_required(func):
    @wraps(func)
    def inner(*args, **kwargs):

        if "user_id" not in session:
            return redirect("/login")

        return func(*args, **kwargs)

    return inner
