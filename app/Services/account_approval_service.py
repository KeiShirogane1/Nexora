import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from app.Models.db import get_db_connection
from app.Services.email_service import (
    send_account_approved_email,
    send_account_rejected_email,
)


AUTO_APPROVAL_MINUTES = 5
AUTO_APPROVAL_SECONDS = AUTO_APPROVAL_MINUTES * 60
WORKER_INTERVAL_SECONDS = 10
PENDING_ROLES = ("pending_student", "pending_supervisor")
TARGET_ROLES = {
    "pending_student": "student",
    "pending_supervisor": "supervisor",
}


def _utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def _approval_deadline(created_at):
    created = _parse_datetime(created_at)
    if not created:
        return None
    return created + timedelta(seconds=AUTO_APPROVAL_SECONDS)


def get_pending_account_view(user):
    created_at = user.get("created_at") if hasattr(user, "get") else user["created_at"]
    role = user.get("role") if hasattr(user, "get") else user["role"]
    deadline = _approval_deadline(created_at)
    now = _utc_now_naive()

    remaining_seconds = (
        max(0, int(math.ceil((deadline - now).total_seconds())))
        if deadline
        else AUTO_APPROVAL_SECONDS
    )

    account_type = "Student" if role == "pending_student" else "Supervisor"

    if deadline:
        deadline_iso = (
            deadline.replace(tzinfo=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    else:
        deadline_iso = (
            (now + timedelta(seconds=AUTO_APPROVAL_SECONDS))
            .replace(tzinfo=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    created = _parse_datetime(created_at)
    created_display = (
        created.strftime("%b %d, %Y • %I:%M %p UTC").lstrip("0")
        if created
        else "Just now"
    )

    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role": role,
        "account_type": account_type,
        "created_at": created_at,
        "created_at_display": created_display,
        "approval_deadline_iso": deadline_iso,
        "remaining_seconds": remaining_seconds,
    }


def approve_pending_user(user_id, expected_pending_role=None, automatic=False):
    conn = get_db_connection()
    cursor = conn.cursor()
    approved_user = None

    try:
        cursor.execute(
            """
            SELECT id, username, email, role
            FROM users
            WHERE id = ?
            AND role IN ('pending_student', 'pending_supervisor')
            """,
            (user_id,),
        )
        user = cursor.fetchone()

        if not user:
            return None

        pending_role = user["role"]
        if expected_pending_role and pending_role != expected_pending_role:
            return None

        target_role = TARGET_ROLES.get(pending_role)
        if not target_role:
            return None

        cursor.execute(
            """
            UPDATE users
            SET role = ?
            WHERE id = ?
            AND role = ?
            """,
            (target_role, user_id, pending_role),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            return None

        conn.commit()
        approved_user = {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": target_role,
            "automatic": automatic,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    if approved_user and approved_user["email"]:
        try:
            send_account_approved_email(
                approved_user["email"],
                approved_user["username"],
                approved_user["role"],
                automatic=automatic,
            )
        except Exception as exc:
            print(
                "Account approval email failed for user",
                approved_user["id"],
                ":",
                exc,
            )

    return approved_user


def reject_pending_user(user_id, expected_pending_role=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    rejected_user = None

    try:
        cursor.execute(
            """
            SELECT id, username, email, role
            FROM users
            WHERE id = ?
            AND role IN ('pending_student', 'pending_supervisor')
            """,
            (user_id,),
        )
        user = cursor.fetchone()

        if not user:
            return None

        pending_role = user["role"]
        if expected_pending_role and pending_role != expected_pending_role:
            return None

        cursor.execute(
            """
            UPDATE users
            SET role = 'rejected'
            WHERE id = ?
            AND role = ?
            """,
            (user_id, pending_role),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            return None

        conn.commit()
        rejected_user = {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "account_type": (
                "student"
                if pending_role == "pending_student"
                else "supervisor"
            ),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    if rejected_user and rejected_user["email"]:
        try:
            send_account_rejected_email(
                rejected_user["email"],
                rejected_user["username"],
                rejected_user["account_type"],
            )
        except Exception as exc:
            print(
                "Account rejection email failed for user",
                rejected_user["id"],
                ":",
                exc,
            )

    return rejected_user


def maybe_auto_approve_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id, role, created_at
            FROM users
            WHERE id = ?
            AND role IN ('pending_student', 'pending_supervisor')
            """,
            (user_id,),
        )
        user = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not user:
        return None

    deadline = _approval_deadline(user["created_at"])
    if not deadline or deadline > _utc_now_naive():
        return None

    return approve_pending_user(
        user["id"],
        expected_pending_role=user["role"],
        automatic=True,
    )


def process_due_pending_accounts(limit=100):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id, role, created_at
            FROM users
            WHERE role IN ('pending_student', 'pending_supervisor')
            AND created_at IS NOT NULL
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        pending_rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    now = _utc_now_naive()
    approved = []

    for user in pending_rows:
        deadline = _approval_deadline(user["created_at"])
        if not deadline or deadline > now:
            continue

        result = approve_pending_user(
            user["id"],
            expected_pending_role=user["role"],
            automatic=True,
        )
        if result:
            approved.append(result)

    return approved


def start_account_approval_worker(app):
    enabled = os.environ.get(
        "NEXORA_AUTO_APPROVAL_ENABLED",
        "true",
    ).strip().lower() not in ("0", "false", "no", "off")

    if not enabled:
        app.logger.info("Nexora automatic account approval worker is disabled.")
        return

    if app.extensions.get("nexora_account_approval_worker_started"):
        return

    app.extensions["nexora_account_approval_worker_started"] = True

    def worker():
        while True:
            try:
                process_due_pending_accounts()
            except Exception as exc:
                app.logger.warning(
                    "Automatic account approval check failed: %s",
                    exc,
                )
            time.sleep(WORKER_INTERVAL_SECONDS)

    thread = threading.Thread(
        target=worker,
        name="nexora-account-approval",
        daemon=True,
    )
    thread.start()
    app.logger.info(
        "Nexora automatic account approval worker started (%s-minute window).",
        AUTO_APPROVAL_MINUTES,
    )
