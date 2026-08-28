from database.db import get_db_connection

ALLOWED_TYPES = {"info", "success", "warning", "error", "task", "feedback", "system"}

MAX_TITLE_LEN = 255
MAX_MESSAGE_LEN = 2000
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _sanitize_type(notification_type):
    if not notification_type:
        return "info"
    t = str(notification_type).strip().lower()
    return t if t in ALLOWED_TYPES else "info"


def create_notification(
    user_id,
    title,
    message,
    notification_type="info",
    link_url=None,
):
    if not user_id:
        raise ValueError("user_id is required")
    if not title or not str(title).strip():
        raise ValueError("title is required")
    if not message or not str(message).strip():
        raise ValueError("message is required")

    title = str(title).strip()[:MAX_TITLE_LEN]
    message = str(message).strip()[:MAX_MESSAGE_LEN]
    notification_type = _sanitize_type(notification_type)
    if link_url is not None:
        link_url = str(link_url).strip()[:500] or None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # verify user exists to avoid orphan FK (sqlite FK may be off, so check manually)
        cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if not cursor.fetchone():
            raise ValueError(f"user_id {user_id} does not exist")

        cursor.execute(
            """
            INSERT INTO notifications
            (user_id, title, message, notification_type, link_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, title, message, notification_type, link_url),
        )
        conn.commit()
        # postgres HybridRow etc: lastrowid available via cursor
        try:
            return cursor.lastrowid
        except Exception:
            # fallback for psycopg2 returning id via RETURNING would need separate path; keep None
            return None
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_user_notifications(user_id, limit=DEFAULT_LIMIT, offset=0, unread_only=False):
    if not user_id:
        return []
    try:
        limit = int(limit)
    except Exception:
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))
    try:
        offset = int(offset)
    except Exception:
        offset = 0
    offset = max(0, offset)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if unread_only:
            cursor.execute(
                """
                SELECT id, title, message, notification_type, is_read, link_url, created_at
                FROM notifications
                WHERE user_id = ? AND is_read = 0
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            )
        else:
            cursor.execute(
                """
                SELECT id, title, message, notification_type, is_read, link_url, created_at
                FROM notifications
                WHERE user_id = ?
                ORDER BY is_read ASC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            )
        rows = cursor.fetchall()
        return rows
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_unread_count(user_id):
    if not user_id:
        return 0
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM notifications
            WHERE user_id = ? AND is_read = 0
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def mark_notification_read(notification_id, user_id=None):
    if not notification_id:
        return False
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute(
                """
                UPDATE notifications
                SET is_read = 1
                WHERE id = ? AND user_id = ?
                """,
                (notification_id, user_id),
            )
        else:
            cursor.execute(
                """
                UPDATE notifications
                SET is_read = 1
                WHERE id = ?
                """,
                (notification_id,),
            )
        conn.commit()
        # rowcount available on both sqlite3 and PostgresCursor wrapper
        try:
            return cursor.rowcount > 0
        except Exception:
            return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def mark_all_read(user_id):
    if not user_id:
        return 0
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE notifications
            SET is_read = 1
            WHERE user_id = ? AND is_read = 0
            """,
            (user_id,),
        )
        conn.commit()
        try:
            return cursor.rowcount
        except Exception:
            return 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def delete_notification(notification_id, user_id=None):
    if not notification_id:
        return False
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute(
                "DELETE FROM notifications WHERE id = ? AND user_id = ?",
                (notification_id, user_id),
            )
        else:
            cursor.execute(
                "DELETE FROM notifications WHERE id = ?", (notification_id,)
            )
        conn.commit()
        try:
            return cursor.rowcount > 0
        except Exception:
            return True
    finally:
        try:
            conn.close()
        except Exception:
            pass
