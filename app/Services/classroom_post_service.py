from datetime import datetime

from app.Models.db import get_db_connection


def _row_value(row, key, index, default=None):
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


def _format_post_datetime(value):
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


def get_classroom_announcements(classroom_id):
    try:
        classroom_id = int(classroom_id)
    except (TypeError, ValueError):
        return []

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                cp.id,
                cp.title,
                cp.body,
                COALESCE(cp.post_type, 'announcement') AS post_type,
                cp.created_at,
                COALESCE(author.username, 'Supervisor') AS author_name,
                COALESCE(author.role, 'supervisor') AS author_role
            FROM classroom_posts cp
            LEFT JOIN users author ON author.id = cp.author_id
            WHERE cp.classroom_id = ?
            ORDER BY cp.created_at DESC, cp.id DESC
            """,
            (classroom_id,),
        ).fetchall()
    finally:
        conn.close()

    announcements = []
    for row in rows:
        post_type = str(_row_value(row, "post_type", 3, "announcement") or "announcement")
        author_role = str(_row_value(row, "author_role", 6, "supervisor") or "supervisor")
        created_at = _row_value(row, "created_at", 4, None)
        announcements.append(
            {
                "id": int(_row_value(row, "id", 0, 0) or 0),
                "title": _row_value(row, "title", 1, "") or "",
                "body": _row_value(row, "body", 2, "") or "",
                "post_type": post_type,
                "post_type_label": post_type.replace("_", " ").title(),
                "created_at": created_at,
                "created_at_display": _format_post_datetime(created_at),
                "author_name": _row_value(row, "author_name", 5, "Supervisor") or "Supervisor",
                "author_role": author_role,
                "author_role_label": (
                    "Supervisor"
                    if author_role.lower() == "supervisor"
                    else author_role.replace("_", " ").title()
                ),
            }
        )
    return announcements
