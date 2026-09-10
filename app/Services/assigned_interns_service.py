"""Supervisor-wide Assigned Interns read model.

This view keeps current Intern Classroom placements authoritative while retaining
legacy admin-assigned interns as a compatibility fallback until they are enrolled
in an Intern Classroom.
"""

from app.Models.db import get_db_connection
from app.Services.classroom_roster_service import get_supervisor_classroom_roster


def _value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except AttributeError:
        pass
    try:
        value = row[index]
        return default if value is None else value
    except (IndexError, KeyError, TypeError):
        return default


def _display_name(row):
    first_name = str(_value(row, "first_name", 3, "") or "").strip()
    middle_name = str(_value(row, "middle_name", 4, "") or "").strip()
    last_name = str(_value(row, "last_name", 5, "") or "").strip()
    username = str(_value(row, "username", 1, "") or "").strip()
    parts = [part for part in (first_name, middle_name, last_name) if part]
    return " ".join(parts) if parts else username or "Intern"


def _student_view(student):
    return {
        "id": int(student.get("id") or 0),
        "username": student.get("username") or "",
        "email_address": student.get("email_address") or "",
        "display_name": student.get("display_name") or student.get("username") or "Intern",
        "student_number": student.get("student_number") or "",
        "major_program": student.get("major_program") or "",
        "grade_year": student.get("grade_year") or "",
        "profile_completed": bool(student.get("profile_completed")),
        "rendered_hours": student.get("rendered_hours", 0),
        "required_hours": student.get("required_hours"),
        "remaining_hours": student.get("remaining_hours"),
        "progress_percentage": student.get("progress_percentage"),
        "roster_status": student.get("roster_status") or "Enrolled",
        "roster_status_key": student.get("roster_status_key") or "enrolled",
        "daily_average_star": student.get("daily_average_star"),
        "daily_average_percentage": student.get("daily_average_percentage"),
        "rated_days": student.get("rated_days", 0),
        "logbook_count": student.get("logbook_count", 0),
        "pending_logbook_count": student.get("pending_logbook_count", 0),
        "revision_logbook_count": student.get("revision_logbook_count", 0),
    }


def get_supervisor_assigned_interns(supervisor_id):
    """Return Supervisor classrooms with their enrolled interns.

    The classroom-first collection powers the Assigned Interns directory while
    the legacy intern-first collection remains available for compatibility with
    existing callers. Classroom-scoped OJT evidence is never combined across
    placements.
    """
    try:
        supervisor_id = int(supervisor_id)
    except (TypeError, ValueError):
        return {
            "classrooms": [],
            "interns": [],
            "legacy_interns": [],
            "summary": {
                "total_interns": 0,
                "classroom_count": 0,
                "classroom_placements": 0,
                "pending_reviews": 0,
                "legacy_only": 0,
            },
        }

    conn = get_db_connection()
    try:
        classrooms = conn.execute(
            """
            SELECT
                c.id,
                c.name,
                c.section,
                COALESCE(c.archived, 0) AS archived,
                COALESCE(cid.company_name, '') AS company_name,
                COALESCE(cid.internship_title, '') AS internship_title,
                COALESCE(cid.work_arrangement, '') AS work_arrangement,
                COALESCE(cid.location, '') AS location
            FROM classrooms c
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.supervisor_id = ?
            ORDER BY COALESCE(c.archived, 0), LOWER(c.name), c.id
            """,
            (supervisor_id,),
        ).fetchall()

        legacy_rows = conn.execute(
            """
            SELECT
                u.id,
                u.username,
                u.email,
                COALESCE(sp.first_name, '') AS first_name,
                COALESCE(sp.middle_name, '') AS middle_name,
                COALESCE(sp.last_name, '') AS last_name,
                COALESCE(sp.student_id, '') AS student_number,
                COALESCE(sp.major_program, '') AS major_program,
                COALESCE(sp.grade_year, '') AS grade_year,
                COALESCE(sp.profile_completed, 0) AS profile_completed
            FROM student_assignments sa
            JOIN users u ON u.id = sa.student_id
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE sa.supervisor_id = ?
            ORDER BY LOWER(u.username), u.id
            """,
            (supervisor_id,),
        ).fetchall()
    finally:
        conn.close()

    interns_by_id = {}
    classroom_groups = []
    classroom_placements = 0
    classrooms_with_interns = 0
    pending_reviews = 0

    for classroom in classrooms:
        classroom_id = int(_value(classroom, "id", 0, 0) or 0)
        if not classroom_id:
            continue

        roster = get_supervisor_classroom_roster(supervisor_id, classroom_id)
        students = roster.get("students") if roster.get("ok") else []
        archived = bool(_value(classroom, "archived", 3, 0))
        if students and not archived:
            classrooms_with_interns += 1

        classroom_data = {
            "class_id": classroom_id,
            "classroom_name": _value(classroom, "name", 1, "") or "Intern Classroom",
            "section": _value(classroom, "section", 2, "") or "",
            "archived": archived,
            "company_name": _value(classroom, "company_name", 4, "") or "",
            "internship_title": _value(classroom, "internship_title", 5, "") or "",
            "work_arrangement": _value(classroom, "work_arrangement", 6, "") or "",
            "location": _value(classroom, "location", 7, "") or "",
        }
        classroom_group = dict(classroom_data)
        classroom_group["interns"] = []

        for student in students:
            student_data = _student_view(student)
            student_id = student_data["id"]
            if not student_id:
                continue

            classroom_group["interns"].append(student_data)
            classroom_placements += 1
            pending_reviews += int(student_data.get("pending_logbook_count") or 0)

            intern = interns_by_id.get(student_id)
            if not intern:
                intern = {
                    "id": student_id,
                    "username": student_data["username"],
                    "email_address": student_data["email_address"],
                    "display_name": student_data["display_name"],
                    "student_number": student_data["student_number"],
                    "major_program": student_data["major_program"],
                    "grade_year": student_data["grade_year"],
                    "profile_completed": student_data["profile_completed"],
                    "legacy_assigned": False,
                    "placements": [],
                }
                interns_by_id[student_id] = intern

            placement = dict(classroom_data)
            placement.update(
                {
                    "rendered_hours": student_data["rendered_hours"],
                    "required_hours": student_data["required_hours"],
                    "remaining_hours": student_data["remaining_hours"],
                    "progress_percentage": student_data["progress_percentage"],
                    "roster_status": student_data["roster_status"],
                    "roster_status_key": student_data["roster_status_key"],
                    "daily_average_star": student_data["daily_average_star"],
                    "daily_average_percentage": student_data["daily_average_percentage"],
                    "rated_days": student_data["rated_days"],
                    "logbook_count": student_data["logbook_count"],
                    "pending_logbook_count": student_data["pending_logbook_count"],
                    "revision_logbook_count": student_data["revision_logbook_count"],
                }
            )
            intern["placements"].append(placement)

        classroom_group["intern_count"] = len(classroom_group["interns"])
        classroom_groups.append(classroom_group)

    for row in legacy_rows:
        student_id = int(_value(row, "id", 0, 0) or 0)
        if not student_id:
            continue

        intern = interns_by_id.get(student_id)
        if intern:
            intern["legacy_assigned"] = True
            continue

        interns_by_id[student_id] = {
            "id": student_id,
            "username": _value(row, "username", 1, "") or "",
            "email_address": _value(row, "email", 2, "") or "",
            "display_name": _display_name(row),
            "student_number": _value(row, "student_number", 6, "") or "",
            "major_program": _value(row, "major_program", 7, "") or "",
            "grade_year": _value(row, "grade_year", 8, "") or "",
            "profile_completed": bool(_value(row, "profile_completed", 9, 0)),
            "legacy_assigned": True,
            "placements": [],
        }

    interns = list(interns_by_id.values())
    for intern in interns:
        placements = intern.get("placements") or []
        intern["classroom_count"] = len(placements)
        intern["is_legacy_only"] = not placements and bool(intern.get("legacy_assigned"))
        intern["has_active_clock_in"] = any(
            placement.get("roster_status_key") == "active" for placement in placements
        )

    interns.sort(key=lambda item: (str(item.get("display_name") or "").lower(), item.get("id") or 0))
    legacy_interns = [intern for intern in interns if intern.get("is_legacy_only")]

    return {
        "classrooms": classroom_groups,
        "interns": interns,
        "legacy_interns": legacy_interns,
        "summary": {
            "total_interns": len(interns),
            "classroom_count": classrooms_with_interns,
            "classroom_placements": classroom_placements,
            "pending_reviews": pending_reviews,
            "legacy_only": len(legacy_interns),
        },
    }
