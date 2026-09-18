import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from app.Models.db import get_db_connection, using_postgres
from app.Services.email_service import (
    send_account_appeal_access_email,
    send_account_appeal_decision_email,
    send_account_removed_email,
    send_admin_appeal_submitted_email,
    send_appeal_received_email,
    send_account_status_email,
)
from app.Services.notification_service import create_notification
from app.Services.password_security import hash_password, verify_password


APPEAL_WINDOW_HOURS = 24
APPEAL_WINDOW_SECONDS = APPEAL_WINDOW_HOURS * 60 * 60
APPEAL_WORKER_INTERVAL_SECONDS = 60


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
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _base_url():
    return os.environ.get("APP_BASE_URL", "").strip().rstrip("/")


def _role_label(role):
    role = str(role or "").replace("pending_", "")
    return "Supervisor" if role == "supervisor" else "Student"


def _format_utc(value):
    parsed = _parse_datetime(value)
    if not parsed:
        return "Unavailable"
    return parsed.strftime("%b %d, %Y • %I:%M %p UTC").lstrip("0")


def _deadline_iso(value):
    parsed = _parse_datetime(value)
    if not parsed:
        return ""
    return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_account_appeal_schema():
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_user_trash (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER UNIQUE,
                    username TEXT,
                    email TEXT,
                    role TEXT,
                    deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    action_type TEXT DEFAULT 'legacy',
                    admin_reason TEXT,
                    appeal_status TEXT DEFAULT 'legacy',
                    appeal_reason TEXT,
                    appeal_deadline TIMESTAMP,
                    appealed_at TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewed_by INTEGER
                )
            """)
            for sql in (
                "ALTER TABLE admin_user_trash ADD COLUMN IF NOT EXISTS action_type TEXT DEFAULT 'legacy'",
                "ALTER TABLE admin_user_trash ADD COLUMN IF NOT EXISTS admin_reason TEXT",
                "ALTER TABLE admin_user_trash ADD COLUMN IF NOT EXISTS appeal_status TEXT DEFAULT 'legacy'",
                "ALTER TABLE admin_user_trash ADD COLUMN IF NOT EXISTS appeal_reason TEXT",
                "ALTER TABLE admin_user_trash ADD COLUMN IF NOT EXISTS appeal_deadline TIMESTAMP",
                "ALTER TABLE admin_user_trash ADD COLUMN IF NOT EXISTS appealed_at TIMESTAMP",
                "ALTER TABLE admin_user_trash ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP",
                "ALTER TABLE admin_user_trash ADD COLUMN IF NOT EXISTS reviewed_by INTEGER",
            ):
                conn.execute(sql)
        else:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_user_trash (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE,
                    username TEXT,
                    email TEXT,
                    role TEXT,
                    deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    action_type TEXT DEFAULT 'legacy',
                    admin_reason TEXT,
                    appeal_status TEXT DEFAULT 'legacy',
                    appeal_reason TEXT,
                    appeal_deadline TIMESTAMP,
                    appealed_at TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewed_by INTEGER
                )
            """)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(admin_user_trash)").fetchall()}
            additions = {
                "action_type": "TEXT DEFAULT 'legacy'",
                "admin_reason": "TEXT",
                "appeal_status": "TEXT DEFAULT 'legacy'",
                "appeal_reason": "TEXT",
                "appeal_deadline": "TIMESTAMP",
                "appealed_at": "TIMESTAMP",
                "reviewed_at": "TIMESTAMP",
                "reviewed_by": "INTEGER",
            }
            for name, definition in additions.items():
                if name not in cols:
                    conn.execute(f"ALTER TABLE admin_user_trash ADD COLUMN {name} {definition}")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_user_trash_appeal_status ON admin_user_trash(appeal_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_user_trash_appeal_deadline ON admin_user_trash(appeal_deadline)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _case_select():
    return """
        SELECT id,user_id,username,email,role,deleted_at,
               action_type,admin_reason,appeal_status,appeal_reason,
               appeal_deadline,appealed_at,reviewed_at,reviewed_by
        FROM admin_user_trash
    """


def _row_to_case(row):
    if not row:
        return None
    keys = (
        "id","user_id","username","email","role","deleted_at",
        "action_type","admin_reason","appeal_status","appeal_reason",
        "appeal_deadline","appealed_at","reviewed_at","reviewed_by",
    )
    data = {key: row[key] if hasattr(row, "keys") and key in row.keys() else row[i] for i, key in enumerate(keys)}
    deadline = _parse_datetime(data.get("appeal_deadline"))
    remaining = max(0, int((deadline - _utc_now_naive()).total_seconds())) if deadline else 0
    data.update({
        "account_type": _role_label(data.get("role")),
        "deadline_iso": _deadline_iso(data.get("appeal_deadline")),
        "deadline_display": _format_utc(data.get("appeal_deadline")),
        "created_display": _format_utc(data.get("deleted_at")),
        "appealed_display": _format_utc(data.get("appealed_at")),
        "remaining_seconds": remaining,
    })
    return data


def get_account_case(user_id):
    if not user_id:
        return None
    conn = get_db_connection()
    try:
        return _row_to_case(conn.execute(_case_select()+" WHERE user_id=? LIMIT 1",(user_id,)).fetchone())
    finally:
        conn.close()


def open_account_appeal_case(user_id, action_type="deactivated", admin_reason=None):
    ensure_account_appeal_schema()
    now = _utc_now_naive()
    deadline = now + timedelta(hours=APPEAL_WINDOW_HOURS)
    conn = get_db_connection()
    try:
        user = conn.execute("""
            SELECT id,username,email,role FROM users
            WHERE id=? AND role!='admin' AND role!='deleted' LIMIT 1
        """,(user_id,)).fetchone()
        if not user:
            return None
        conn.execute("""
            UPDATE users
            SET status='inactive',session_version=COALESCE(session_version,0)+1
            WHERE id=? AND role!='admin'
        """,(user_id,))
        exists = conn.execute("SELECT id FROM admin_user_trash WHERE user_id=? LIMIT 1",(user_id,)).fetchone()
        if exists:
            conn.execute("""
                UPDATE admin_user_trash
                SET username=?,email=?,role=?,deleted_at=?,action_type=?,admin_reason=?,
                    appeal_status='eligible',appeal_reason=NULL,appeal_deadline=?,
                    appealed_at=NULL,reviewed_at=NULL,reviewed_by=NULL
                WHERE user_id=?
            """,(user["username"],user["email"],user["role"],now,action_type,(admin_reason or "").strip() or None,deadline,user_id))
        else:
            conn.execute("""
                INSERT INTO admin_user_trash
                (user_id,username,email,role,deleted_at,action_type,admin_reason,appeal_status,appeal_deadline)
                VALUES (?,?,?,?,?,?,?,'eligible',?)
            """,(user_id,user["username"],user["email"],user["role"],now,action_type,(admin_reason or "").strip() or None,deadline))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    case = get_account_case(user_id)
    if case and case.get("email"):
        try:
            appeal_url = f"{_base_url()}/account/appeal" if _base_url() else "/account/appeal"
            send_account_appeal_access_email(
                case["email"],case["username"],case["account_type"],
                case["action_type"],case["deadline_display"],appeal_url,
            )
        except Exception:
            pass
    return case


def authenticate_appeal_account(identifier, password):
    identifier = (identifier or "").strip()
    if not identifier or not password:
        return None, "Enter your username/email and password."
    process_expired_account_cases()
    conn = get_db_connection()
    try:
        row = conn.execute("""
            SELECT u.id,u.password
            FROM users u
            JOIN admin_user_trash t ON t.user_id=u.id
            WHERE (u.username=? OR LOWER(u.email)=LOWER(?))
              AND u.status='inactive'
              AND u.role NOT IN ('admin','deleted')
              AND t.appeal_status IN ('eligible','submitted')
            LIMIT 1
        """,(identifier,identifier)).fetchone()
    finally:
        conn.close()
    if not row:
        return None, "No appeal-eligible inactive account was found."
    if not verify_password(row["password"], password):
        return None, "Invalid username/email or password."
    case = get_account_case(row["id"])
    if not case:
        return None, "Appeal case not found."
    if case["appeal_status"]=="eligible" and case["remaining_seconds"]<=0:
        purge_account_identity(case["user_id"],"appeal_window_expired",True)
        return None, "The 24-hour appeal window has expired."
    return case, None


def submit_account_appeal(user_id, reason):
    reason = (reason or "").strip()
    if len(reason)<20:
        return None, "Please provide at least 20 characters explaining your appeal."
    if len(reason)>2000:
        return None, "Appeal reason must be 2,000 characters or fewer."
    now = _utc_now_naive()
    conn = get_db_connection()
    try:
        cur = conn.execute("""
            UPDATE admin_user_trash
            SET appeal_status='submitted',appeal_reason=?,appealed_at=?
            WHERE user_id=? AND appeal_status='eligible'
              AND appeal_deadline IS NOT NULL AND appeal_deadline>?
        """,(reason,now,user_id,now))
        if cur.rowcount!=1:
            conn.rollback()
            return None, "This appeal can no longer be submitted."
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    case = get_account_case(user_id)
    review_url = f"{_base_url()}/admin/appeals?case={case['id']}" if _base_url() else f"/admin/appeals?case={case['id']}"
    conn = get_db_connection()
    try:
        admins = conn.execute("""
            SELECT id,username,email FROM users
            WHERE role='admin' AND COALESCE(status,'active')!='inactive'
        """).fetchall()
    finally:
        conn.close()

    for admin in admins:
        try:
            create_notification(
                admin["id"],"New account appeal",
                f"{case['username']} submitted an appeal for their {case['account_type'].lower()} account.",
                "warning",f"/admin/appeals?case={case['id']}",
            )
        except Exception:
            pass
        if admin["email"]:
            try:
                send_admin_appeal_submitted_email(
                    admin["email"],admin["username"],case["username"],case["email"],
                    case["account_type"],reason,review_url,
                )
            except Exception:
                pass
    if case.get("email"):
        try:
            send_appeal_received_email(case["email"],case["username"],case["account_type"])
        except Exception:
            pass
    return case, None


def get_admin_appeal_cases():
    process_expired_account_cases()
    conn = get_db_connection()
    try:
        rows = conn.execute(_case_select()+"""
            WHERE appeal_status IN ('eligible','submitted')
            ORDER BY CASE WHEN appeal_status='submitted' THEN 0 ELSE 1 END,
                     COALESCE(appealed_at,deleted_at) DESC
        """).fetchall()
        return [_row_to_case(row) for row in rows]
    finally:
        conn.close()


def get_submitted_appeal_count():
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT COUNT(*) FROM admin_user_trash WHERE appeal_status='submitted'").fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        conn.close()


def reactivate_account(user_id, notify=True):
    conn = get_db_connection()
    try:
        user = conn.execute("""
            SELECT id,username,email,role FROM users
            WHERE id=? AND role NOT IN ('admin','deleted') LIMIT 1
        """,(user_id,)).fetchone()
        if not user:
            return None
        conn.execute("""
            UPDATE users SET status='active',session_version=COALESCE(session_version,0)+1
            WHERE id=?
        """,(user_id,))
        conn.execute("DELETE FROM admin_user_trash WHERE user_id=?",(user_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    result={"id":user["id"],"username":user["username"],"email":user["email"],"role":user["role"],"account_type":_role_label(user["role"])}
    if notify and result.get("email"):
        try:
            send_account_status_email(result["email"],result["username"],result["account_type"].lower(),True)
        except Exception:
            pass
    return result


def approve_account_appeal(case_id, admin_id):
    conn=get_db_connection()
    try:
        case=_row_to_case(conn.execute(_case_select()+" WHERE id=? AND appeal_status='submitted' LIMIT 1",(case_id,)).fetchone())
    finally:
        conn.close()
    if not case or not reactivate_account(case["user_id"],False):
        return None
    if case.get("email"):
        try:
            send_account_appeal_decision_email(case["email"],case["username"],case["account_type"],True)
        except Exception:
            pass
    return case


def _safe_delete_personal_rows(conn, table, column, user_id):
    conn.execute("SAVEPOINT nx_appeal_personal")
    try:
        conn.execute(f"DELETE FROM {table} WHERE {column}=?",(user_id,))
        conn.execute("RELEASE SAVEPOINT nx_appeal_personal")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT nx_appeal_personal")
            conn.execute("RELEASE SAVEPOINT nx_appeal_personal")
        except Exception:
            pass


def purge_account_identity(user_id, removal_reason="appeal_window_expired", notify=True):
    conn=get_db_connection()
    try:
        user=conn.execute("""
            SELECT id,username,email,role FROM users
            WHERE id=? AND role NOT IN ('admin','deleted') LIMIT 1
        """,(user_id,)).fetchone()
        if not user:
            conn.execute("DELETE FROM admin_user_trash WHERE user_id=?",(user_id,))
            conn.commit()
            return None
        snapshot={"id":user["id"],"username":user["username"],"email":user["email"],"role":user["role"],"account_type":_role_label(user["role"])}
        for table,column in (
            ("password_reset_tokens","user_id"),
            ("change_verification_codes","user_id"),
            ("notifications","user_id"),
            ("student_profiles","user_id"),
            ("supervisor_profiles","user_id"),
        ):
            _safe_delete_personal_rows(conn,table,column,user_id)
        conn.execute("""
            UPDATE users
            SET username=?,email=NULL,password=?,role='deleted',status='inactive',
                profile_picture=NULL,session_version=COALESCE(session_version,0)+1
            WHERE id=? AND role!='admin'
        """,(f"deleted_{user_id}",hash_password(secrets.token_urlsafe(48)),user_id))
        conn.execute("DELETE FROM admin_user_trash WHERE user_id=?",(user_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if notify and snapshot.get("email"):
        try:
            send_account_removed_email(snapshot["email"],snapshot["username"],snapshot["account_type"],removal_reason)
        except Exception:
            pass
    return snapshot


def deny_account_appeal(case_id, admin_id):
    conn=get_db_connection()
    try:
        case=_row_to_case(conn.execute(_case_select()+" WHERE id=? AND appeal_status='submitted' LIMIT 1",(case_id,)).fetchone())
        if not case:
            return None
        conn.execute("""
            UPDATE admin_user_trash
            SET appeal_status='denied',reviewed_at=?,reviewed_by=?
            WHERE id=? AND appeal_status='submitted'
        """,(_utc_now_naive(),admin_id,case_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if case.get("email"):
        try:
            send_account_appeal_decision_email(case["email"],case["username"],case["account_type"],False)
        except Exception:
            pass
    purge_account_identity(case["user_id"],"appeal_denied",False)
    return case


def process_expired_account_cases(limit=100):
    now=_utc_now_naive()
    conn=get_db_connection()
    try:
        rows=conn.execute("""
            SELECT user_id FROM admin_user_trash
            WHERE appeal_status='eligible'
              AND appeal_deadline IS NOT NULL
              AND appeal_deadline<=?
            ORDER BY appeal_deadline ASC LIMIT ?
        """,(now,limit)).fetchall()
        ids=[int(row[0]) for row in rows]
    finally:
        conn.close()
    removed=0
    for user_id in ids:
        if purge_account_identity(user_id,"appeal_window_expired",True):
            removed+=1
    return removed


def start_account_appeal_worker(app):
    if os.environ.get("NEXORA_ACCOUNT_APPEAL_ENABLED","true").strip().lower() in ("0","false","no","off"):
        return
    if app.extensions.get("nexora_account_appeal_worker_started"):
        return
    app.extensions["nexora_account_appeal_worker_started"]=True
    def worker():
        while True:
            try:
                process_expired_account_cases()
            except Exception as exc:
                app.logger.warning("Account appeal expiry check failed: %s",exc)
            time.sleep(APPEAL_WORKER_INTERVAL_SECONDS)
    threading.Thread(target=worker,name="nexora-account-appeal",daemon=True).start()
    app.logger.info("Nexora account appeal worker started (%s-hour window).",APPEAL_WINDOW_HOURS)
