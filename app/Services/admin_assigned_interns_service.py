"""Admin-wide Assigned Interns read model.

This intentionally reuses the Supervisor classroom-first read model so Admin sees
exactly the same OJT evidence without bypassing Supervisor ownership checks.
"""

from app.Models.db import get_db_connection
from app.Services.assigned_interns_service import get_supervisor_assigned_interns


def _value(row, key, index=0, default=None):
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


def get_admin_assigned_interns():
    """Return all Supervisor-assigned interns for the Admin read-only directory."""
    conn = get_db_connection()
    try:
        supervisors = conn.execute(
            """
            SELECT u.id, u.username, COALESCE(u.email, '') AS email
            FROM users u
            WHERE u.role = 'supervisor'
              AND (
                    EXISTS (
                        SELECT 1
                        FROM classrooms c
                        WHERE c.supervisor_id = u.id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM student_assignments sa
                        WHERE sa.supervisor_id = u.id
                    )
              )
            ORDER BY LOWER(u.username), u.id
            """
        ).fetchall()
    finally:
        conn.close()

    groups = []
    supervisor_options = []
    intern_state = {}
    classroom_count = 0
    classroom_placements = 0
    pending_reviews = 0

    for row in supervisors:
        supervisor_id = int(_value(row, "id", 0, 0) or 0)
        if not supervisor_id:
            continue

        supervisor_name = str(_value(row, "username", 1, "Supervisor") or "Supervisor")
        supervisor_email = str(_value(row, "email", 2, "") or "")
        context = get_supervisor_assigned_interns(supervisor_id)

        if context.get("interns") or context.get("flat_interns"):
            supervisor_options.append(
                {
                    "id": supervisor_id,
                    "name": supervisor_name,
                    "email": supervisor_email,
                }
            )

        for intern in context.get("flat_interns", []):
            intern_id = int(intern.get("id") or 0)
            if not intern_id:
                continue
            state = intern_state.setdefault(
                intern_id,
                {"has_placement": False, "legacy_assigned": False},
            )
            if intern.get("placements"):
                state["has_placement"] = True
            if intern.get("legacy_assigned"):
                state["legacy_assigned"] = True

        for group in context.get("interns", []):
            admin_group = dict(group)
            admin_group.update(
                {
                    "supervisor_id": supervisor_id,
                    "supervisor_name": supervisor_name,
                    "supervisor_email": supervisor_email,
                }
            )
            groups.append(admin_group)

        summary = context.get("summary") or {}
        classroom_count += int(summary.get("classroom_count") or 0)
        classroom_placements += int(summary.get("classroom_placements") or 0)
        pending_reviews += int(summary.get("pending_reviews") or 0)

    groups.sort(
        key=lambda group: (
            1 if group.get("is_legacy") else 0,
            1 if group.get("archived") else 0,
            str(group.get("supervisor_name") or "").lower(),
            str(group.get("classroom_name") or "").lower(),
            int(group.get("class_id") or 0),
        )
    )

    legacy_only = sum(
        1
        for state in intern_state.values()
        if state.get("legacy_assigned") and not state.get("has_placement")
    )

    return {
        "interns": groups,
        "supervisors": supervisor_options,
        "summary": {
            "total_interns": len(intern_state),
            "classroom_count": classroom_count,
            "classroom_placements": classroom_placements,
            "pending_reviews": pending_reviews,
            "legacy_only": legacy_only,
            "supervisor_count": len(supervisor_options),
        },
    }
