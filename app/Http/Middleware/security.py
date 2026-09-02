from functools import wraps
from flask import session, redirect
from app.Models.db import get_db_connection


def _dashboard_for_role(role):
    return {
        "student": "/student/dashboard",
        "supervisor": "/supervisor/dashboard",
        "admin": "/admin/dashboard",
    }.get(role, "/login")


def _sync_session_identity():
    """Validate the logged-in user's database identity and refresh the session role.

    The session is client-side in Flask, so its role value can become stale after
    an administrator changes an account. Always use the database as the source
    of truth before serving an authenticated request.
    """
    user_id = session.get("user_id")
    if user_id is None:
        return None, redirect("/login")

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT role, status FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        session.clear()
        return None, redirect("/login")

    try:
        actual_role = row["role"]
        status = row["status"]
    except Exception:
        actual_role = row[0]
        status = row[1] if len(row) > 1 else None

    if actual_role not in {"student", "supervisor", "admin"}:
        session.clear()
        return None, redirect("/login")

    if status == "inactive":
        session.clear()
        return None, ("Account deactivated — contact administrator.", 403)

    # Keep the session synchronized for templates and any login-required route.
    session["role"] = actual_role
    return actual_role, None


def role_required(role):

    def wrapper(func):
        @wraps(func)
        def inner(*args, **kwargs):
            actual_role, response = _sync_session_identity()
            if response is not None:
                return response

            if actual_role != role:
                return redirect(_dashboard_for_role(actual_role))

            return func(*args, **kwargs)

        return inner

    return wrapper


def login_required(func):
    @wraps(func)
    def inner(*args, **kwargs):
        _, response = _sync_session_identity()
        if response is not None:
            return response

        return func(*args, **kwargs)

    return inner
