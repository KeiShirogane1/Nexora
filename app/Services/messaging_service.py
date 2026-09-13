"""Authorized direct messaging between Nexora portal roles."""

from datetime import datetime

from app.Models.db import get_db_connection, using_postgres
from app.Services.messaging_schema import ensure_messaging_schema
from app.Services.notification_service import create_notification

MAX_BODY_LEN = 2000
THREAD_LIMIT = 100


def _row_value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except Exception:
        pass
    try:
        value = row[index]
        return default if value is None else value
    except Exception:
        return default


def _serialize_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _user_record(user_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT id, username, role, COALESCE(status, 'active') AS status
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    return row


def _display_name(user_id, role, username):
    conn = get_db_connection()
    try:
        if role == "student":
            row = conn.execute(
                "SELECT first_name, middle_name, last_name FROM student_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        elif role == "supervisor":
            row = conn.execute(
                "SELECT first_name, middle_name, last_name FROM supervisor_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = None
    except Exception:
        row = None
    finally:
        conn.close()

    if row:
        parts = [
            str(_row_value(row, "first_name", 0, "") or "").strip(),
            str(_row_value(row, "middle_name", 1, "") or "").strip(),
            str(_row_value(row, "last_name", 2, "") or "").strip(),
        ]
        name = " ".join(part for part in parts if part)
        if name:
            return name
    return username or role.title()


def _profile_picture(user_id, role):
    conn = get_db_connection()
    try:
        # Student uploads are stored on student_profiles. Supervisor uploads and
        # account-level/Admin photos are stored on users.profile_picture.
        if role == "student":
            row = conn.execute(
                "SELECT profile_picture FROM student_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            profile_picture = str(_row_value(row, "profile_picture", 0, "") or "").strip()
            if profile_picture:
                return profile_picture

        row = conn.execute(
            "SELECT profile_picture FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return str(_row_value(row, "profile_picture", 0, "") or "").strip()
    except Exception:
        return ""
    finally:
        conn.close()


def _contact_from_row(row, unread_count=0, message_count=0, last_message_at=None):
    user_id = int(_row_value(row, "id", 0, 0) or 0)
    username = str(_row_value(row, "username", 1, "") or "")
    role = str(_row_value(row, "role", 2, "") or "")
    return {
        "id": user_id,
        "username": username,
        "role": role,
        "display_name": _display_name(user_id, role, username),
        "profile_picture": _profile_picture(user_id, role),
        "unread_count": int(unread_count or 0),
        "message_count": int(message_count or 0),
        "last_message_at": _serialize_datetime(last_message_at),
    }


def _authorized_contact_rows(user_id, role):
    conn = get_db_connection()
    try:
        if role == "student":
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.role
                FROM users u
                WHERE COALESCE(u.status, 'active') = 'active'
                  AND (
                    (
                      u.role = 'supervisor'
                      AND (
                        EXISTS (
                          SELECT 1
                          FROM classroom_students cs
                          JOIN classrooms c ON c.id = cs.classroom_id
                          WHERE cs.student_id = ?
                            AND c.supervisor_id = u.id
                            AND COALESCE(c.archived, 0) = 0
                        )
                        OR EXISTS (
                          SELECT 1
                          FROM student_assignments sa
                          WHERE sa.student_id = ?
                            AND sa.supervisor_id = u.id
                        )
                      )
                    )
                    OR (
                      u.role = 'student'
                      AND u.id <> ?
                      AND EXISTS (
                        SELECT 1
                        FROM classroom_students mine
                        JOIN classroom_students peer
                          ON peer.classroom_id = mine.classroom_id
                        JOIN classrooms c ON c.id = mine.classroom_id
                        WHERE mine.student_id = ?
                          AND peer.student_id = u.id
                          AND COALESCE(c.archived, 0) = 0
                      )
                    )
                    OR u.role = 'admin'
                  )
                ORDER BY u.role, LOWER(u.username), u.id
                """,
                (user_id, user_id, user_id, user_id),
            ).fetchall()
        elif role == "supervisor":
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.role
                FROM users u
                WHERE COALESCE(u.status, 'active') = 'active'
                  AND (
                    (
                      u.role = 'student'
                      AND (
                        EXISTS (
                          SELECT 1
                          FROM classroom_students cs
                          JOIN classrooms c ON c.id = cs.classroom_id
                          WHERE cs.student_id = u.id
                            AND c.supervisor_id = ?
                            AND COALESCE(c.archived, 0) = 0
                        )
                        OR EXISTS (
                          SELECT 1
                          FROM student_assignments sa
                          WHERE sa.student_id = u.id
                            AND sa.supervisor_id = ?
                        )
                      )
                    )
                    OR u.role = 'admin'
                  )
                ORDER BY u.role, LOWER(u.username), u.id
                """,
                (user_id, user_id),
            ).fetchall()
        elif role == "admin":
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.role
                FROM users u
                WHERE u.id <> ?
                  AND COALESCE(u.status, 'active') = 'active'
                  AND u.role IN ('student', 'supervisor')
                ORDER BY u.role, LOWER(u.username), u.id
                """,
                (user_id,),
            ).fetchall()
        else:
            rows = []
        return rows
    finally:
        conn.close()


def get_authorized_contacts(user_id, target_role=None):
    ensure_messaging_schema()
    user = _user_record(user_id)
    if not user or str(_row_value(user, "status", 3, "")) != "active":
        return []

    role = str(_row_value(user, "role", 2, "") or "")
    rows = _authorized_contact_rows(user_id, role)
    if target_role:
        target_role = str(target_role).strip().lower()
        rows = [row for row in rows if str(_row_value(row, "role", 2, "")) == target_role]

    conn = get_db_connection()
    try:
        contacts = []
        for row in rows:
            contact_id = int(_row_value(row, "id", 0, 0) or 0)
            unread_row = conn.execute(
                """
                SELECT COUNT(*)
                FROM direct_messages
                WHERE sender_id = ?
                  AND recipient_id = ?
                  AND read_at IS NULL
                """,
                (contact_id, user_id),
            ).fetchone()
            thread_row = conn.execute(
                """
                SELECT COUNT(*) AS message_count, MAX(created_at) AS last_message_at
                FROM direct_messages
                WHERE (sender_id = ? AND recipient_id = ?)
                   OR (sender_id = ? AND recipient_id = ?)
                """,
                (user_id, contact_id, contact_id, user_id),
            ).fetchone()
            contact = _contact_from_row(
                row,
                int(_row_value(unread_row, "count", 0, 0) or 0),
                int(_row_value(thread_row, "message_count", 0, 0) or 0),
                _row_value(thread_row, "last_message_at", 1),
            )

            if role == "student" and contact.get("role") == "student":
                classroom_rows = conn.execute(
                    """
                    SELECT DISTINCT c.id, c.name, c.section
                    FROM classroom_students mine
                    JOIN classroom_students peer
                      ON peer.classroom_id = mine.classroom_id
                    JOIN classrooms c ON c.id = mine.classroom_id
                    WHERE mine.student_id = ?
                      AND peer.student_id = ?
                      AND COALESCE(c.archived, 0) = 0
                    ORDER BY LOWER(c.name), c.id
                    """,
                    (user_id, contact_id),
                ).fetchall()
                contact["shared_classrooms"] = [
                    {
                        "id": int(_row_value(classroom_row, "id", 0, 0) or 0),
                        "name": str(_row_value(classroom_row, "name", 1, "") or ""),
                        "section": str(_row_value(classroom_row, "section", 2, "") or ""),
                    }
                    for classroom_row in classroom_rows
                ]

            contacts.append(contact)
        return contacts
    finally:
        conn.close()


def get_authorized_contact(user_id, contact_id):
    try:
        contact_id = int(contact_id)
    except (TypeError, ValueError):
        return None
    for contact in get_authorized_contacts(user_id):
        if contact["id"] == contact_id:
            return contact
    return None


def _message_view(row, user_id):
    sender_id = int(_row_value(row, "sender_id", 1, 0) or 0)
    return {
        "id": int(_row_value(row, "id", 0, 0) or 0),
        "sender_id": sender_id,
        "recipient_id": int(_row_value(row, "recipient_id", 2, 0) or 0),
        "body": str(_row_value(row, "body", 3, "") or ""),
        "created_at": _serialize_datetime(_row_value(row, "created_at", 4)),
        "read_at": _serialize_datetime(_row_value(row, "read_at", 5)),
        "mine": sender_id == int(user_id),
    }


def get_thread(user_id, contact_id, limit=THREAD_LIMIT):
    ensure_messaging_schema()
    contact = get_authorized_contact(user_id, contact_id)
    if not contact:
        return None

    try:
        limit = max(1, min(int(limit), THREAD_LIMIT))
    except Exception:
        limit = THREAD_LIMIT

    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE direct_messages
            SET read_at = CURRENT_TIMESTAMP
            WHERE sender_id = ?
              AND recipient_id = ?
              AND read_at IS NULL
            """,
            (contact["id"], user_id),
        )
        conn.commit()

        rows = conn.execute(
            """
            SELECT id, sender_id, recipient_id, body, created_at, read_at
            FROM direct_messages
            WHERE (sender_id = ? AND recipient_id = ?)
               OR (sender_id = ? AND recipient_id = ?)
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, contact["id"], contact["id"], user_id, limit),
        ).fetchall()
    finally:
        conn.close()

    messages = [_message_view(row, user_id) for row in reversed(rows)]
    contact["unread_count"] = 0
    return {"contact": contact, "messages": messages}


def send_message(sender_id, recipient_id, body):
    ensure_messaging_schema()
    contact = get_authorized_contact(sender_id, recipient_id)
    if not contact:
        raise PermissionError("You are not allowed to message this user.")

    body = str(body or "").strip()
    if not body:
        raise ValueError("Message cannot be empty.")
    if len(body) > MAX_BODY_LEN:
        raise ValueError(f"Message must be {MAX_BODY_LEN} characters or fewer.")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        insert_sql = """
            INSERT INTO direct_messages (sender_id, recipient_id, body)
            VALUES (?, ?, ?)
        """
        if using_postgres():
            insert_sql += " RETURNING id"
        cursor.execute(insert_sql, (sender_id, contact["id"], body))

        if using_postgres():
            row = cursor.fetchone()
            message_id = int(_row_value(row, "id", 0, 0) or 0)
        else:
            message_id = int(cursor.lastrowid)

        conn.commit()
        row = conn.execute(
            """
            SELECT id, sender_id, recipient_id, body, created_at, read_at
            FROM direct_messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    sender = _user_record(sender_id)
    sender_username = str(_row_value(sender, "username", 1, "") or "")
    sender_role = str(_row_value(sender, "role", 2, "") or "")
    sender_name = _display_name(sender_id, sender_role, sender_username)

    try:
        create_notification(
            contact["id"],
            f"New message from {sender_name}",
            body[:180],
            notification_type="info",
            link_url=f"/messages/open/{sender_id}",
        )
    except Exception:
        pass

    return _message_view(row, sender_id)
