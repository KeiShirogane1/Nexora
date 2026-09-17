"""Admin-wide assigned-intern and management-directory read models.

These helpers are read-only. They reuse existing profile, classroom, enrollment, and
legacy assignment data so Admin can display richer directories without introducing
new storage or changing ownership rules.
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


def _display_name(first_name, middle_name, last_name, fallback):
    parts = [
        str(value or "").strip()
        for value in (first_name, middle_name, last_name)
        if str(value or "").strip()
    ]
    return " ".join(parts) if parts else str(fallback or "").strip()


def _class_label(name, section):
    name = str(name or "").strip() or "Classroom"
    section = str(section or "").strip()
    return f"{name} · {section}" if section else name


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
                    EXISTS (SELECT 1 FROM classrooms c WHERE c.supervisor_id = u.id)
                    OR EXISTS (SELECT 1 FROM student_assignments sa WHERE sa.supervisor_id = u.id)
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
            supervisor_options.append({"id": supervisor_id, "name": supervisor_name, "email": supervisor_email})
        for intern in context.get("flat_interns", []):
            intern_id = int(intern.get("id") or 0)
            if not intern_id:
                continue
            state = intern_state.setdefault(intern_id, {"has_placement": False, "legacy_assigned": False})
            if intern.get("placements"):
                state["has_placement"] = True
            if intern.get("legacy_assigned"):
                state["legacy_assigned"] = True
        for group in context.get("interns", []):
            admin_group = dict(group)
            admin_group.update({"supervisor_id": supervisor_id, "supervisor_name": supervisor_name, "supervisor_email": supervisor_email})
            groups.append(admin_group)
        summary = context.get("summary") or {}
        classroom_count += int(summary.get("classroom_count") or 0)
        classroom_placements += int(summary.get("classroom_placements") or 0)
        pending_reviews += int(summary.get("pending_reviews") or 0)

    groups.sort(key=lambda group: (
        1 if group.get("is_legacy") else 0,
        1 if group.get("archived") else 0,
        str(group.get("supervisor_name") or "").lower(),
        str(group.get("classroom_name") or "").lower(),
        int(group.get("class_id") or 0),
    ))
    legacy_only = sum(1 for state in intern_state.values() if state.get("legacy_assigned") and not state.get("has_placement"))
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


def get_admin_student_management_context():
    """Return profile, class, and supervisor metadata for Student Management."""
    conn = get_db_connection()
    try:
        student_rows = conn.execute(
            """
            SELECT u.id, u.username, COALESCE(u.email, '') AS email, u.role,
                   COALESCE(u.status, 'active') AS status,
                   COALESCE(sp.first_name, '') AS first_name,
                   COALESCE(sp.middle_name, '') AS middle_name,
                   COALESCE(sp.last_name, '') AS last_name,
                   COALESCE(sp.student_id, '') AS student_number,
                   COALESCE(sp.major_program, '') AS major_program,
                   COALESCE(sp.grade_year, '') AS grade_year,
                   COALESCE(sp.profile_picture, '') AS profile_picture
            FROM users u
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE u.role IN ('student', 'pending_student')
            ORDER BY LOWER(u.username), u.id
            """
        ).fetchall()
        placement_rows = conn.execute(
            """
            SELECT cs.student_id, c.id AS class_id, c.name AS classroom_name,
                   COALESCE(c.section, '') AS section,
                   COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                   c.supervisor_id, COALESCE(sup.username, '') AS supervisor_name,
                   COALESCE(cid.program, '') AS internship_program
            FROM classroom_students cs
            JOIN classrooms c ON c.id = cs.classroom_id
            LEFT JOIN users sup ON sup.id = c.supervisor_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE COALESCE(c.archived, 0) = 0
            ORDER BY LOWER(c.name), LOWER(COALESCE(c.section, '')), c.id
            """
        ).fetchall()
        assignment_rows = conn.execute(
            """
            SELECT sa.student_id, u.id AS supervisor_id, u.username AS supervisor_name
            FROM student_assignments sa
            JOIN users u ON u.id = sa.supervisor_id
            WHERE u.role = 'supervisor'
            ORDER BY LOWER(u.username), u.id
            """
        ).fetchall()
    finally:
        conn.close()

    students = {}
    for row in student_rows:
        student_id = int(_value(row, "id", 0, 0) or 0)
        if not student_id:
            continue
        username = str(_value(row, "username", 1, "") or "")
        profile_picture = str(_value(row, "profile_picture", 11, "") or "").strip()
        students[student_id] = {
            "id": student_id,
            "username": username,
            "email": str(_value(row, "email", 2, "") or ""),
            "display_name": _display_name(_value(row, "first_name", 5, ""), _value(row, "middle_name", 6, ""), _value(row, "last_name", 7, ""), username),
            "student_number": str(_value(row, "student_number", 8, "") or ""),
            "major_program": str(_value(row, "major_program", 9, "") or ""),
            "grade_year": str(_value(row, "grade_year", 10, "") or ""),
            "status": "pending" if _value(row, "role", 3, "") == "pending_student" else str(_value(row, "status", 4, "active") or "active").lower(),
            "profile_picture_url": f"/uploads/profile_pictures/{profile_picture}" if profile_picture else f"/profile-picture/{student_id}",
            "placements": [],
            "assigned_supervisors": [],
        }

    class_options = {}
    programs = set()
    years = set()
    for student in students.values():
        if student["major_program"]:
            programs.add(student["major_program"])
        if student["grade_year"]:
            years.add(student["grade_year"])

    for row in placement_rows:
        student = students.get(int(_value(row, "student_id", 0, 0) or 0))
        if not student:
            continue
        class_id = int(_value(row, "class_id", 1, 0) or 0)
        classroom_name = str(_value(row, "classroom_name", 2, "") or "")
        section = str(_value(row, "section", 3, "") or "")
        program = str(_value(row, "internship_program", 7, "") or "")
        supervisor_id = int(_value(row, "supervisor_id", 5, 0) or 0)
        supervisor_name = str(_value(row, "supervisor_name", 6, "") or "")
        placement = {
            "id": class_id,
            "name": classroom_name,
            "section": section,
            "label": _class_label(classroom_name, section),
            "classroom_type": str(_value(row, "classroom_type", 4, "classroom") or "classroom"),
            "supervisor_id": supervisor_id,
            "supervisor_name": supervisor_name,
            "program": program,
        }
        student["placements"].append(placement)
        class_options[class_id] = {"id": class_id, "label": placement["label"]}
        if program:
            programs.add(program)
        if supervisor_id and supervisor_name and not any(item["id"] == supervisor_id for item in student["assigned_supervisors"]):
            student["assigned_supervisors"].append({"id": supervisor_id, "name": supervisor_name, "source": "classroom"})

    for row in assignment_rows:
        student = students.get(int(_value(row, "student_id", 0, 0) or 0))
        if not student:
            continue
        supervisor_id = int(_value(row, "supervisor_id", 1, 0) or 0)
        supervisor_name = str(_value(row, "supervisor_name", 2, "") or "")
        if supervisor_id and supervisor_name and not any(item["id"] == supervisor_id for item in student["assigned_supervisors"]):
            student["assigned_supervisors"].append({"id": supervisor_id, "name": supervisor_name, "source": "legacy"})

    result_students = list(students.values())
    for student in result_students:
        student["placements"].sort(key=lambda item: (item["label"].lower(), item["id"]))
        student["assigned_supervisors"].sort(key=lambda item: item["name"].lower())
        student["primary_class"] = student["placements"][0] if student["placements"] else None

    return {
        "students": result_students,
        "classes": sorted(class_options.values(), key=lambda item: item["label"].lower()),
        "programs": sorted(programs, key=str.casefold),
        "years": sorted(years, key=str.casefold),
    }


def get_admin_supervisor_management_context():
    """Return profile, program, classroom, and workload metadata for Supervisor Management."""
    conn = get_db_connection()
    try:
        supervisor_rows = conn.execute(
            """
            SELECT u.id, u.username, COALESCE(u.email, '') AS email, u.role,
                   COALESCE(u.status, 'active') AS status,
                   COALESCE(u.profile_picture, '') AS profile_picture,
                   COALESCE(sp.first_name, '') AS first_name,
                   COALESCE(sp.middle_name, '') AS middle_name,
                   COALESCE(sp.last_name, '') AS last_name,
                   COALESCE(sp.employee_id, '') AS employee_id,
                   COALESCE(sp.job_title, '') AS job_title,
                   COALESCE(sp.department, '') AS department,
                   COALESCE(sp.specialization, '') AS specialization
            FROM users u
            LEFT JOIN supervisor_profiles sp ON sp.user_id = u.id
            WHERE u.role IN ('supervisor', 'pending_supervisor')
            ORDER BY LOWER(u.username), u.id
            """
        ).fetchall()
        class_rows = conn.execute(
            """
            SELECT c.supervisor_id, c.id AS class_id, c.name AS classroom_name,
                   COALESCE(c.section, '') AS section,
                   COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                   COALESCE(cid.program, '') AS program,
                   (SELECT COUNT(*) FROM classroom_students cs WHERE cs.classroom_id = c.id) AS student_count
            FROM classrooms c
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE COALESCE(c.archived, 0) = 0
            ORDER BY LOWER(c.name), LOWER(COALESCE(c.section, '')), c.id
            """
        ).fetchall()
        assigned_rows = conn.execute(
            """
            SELECT supervisor_id, COUNT(*) AS assigned_students
            FROM (
                SELECT c.supervisor_id, cs.student_id
                FROM classrooms c
                JOIN classroom_students cs ON cs.classroom_id = c.id
                WHERE COALESCE(c.archived, 0) = 0
                UNION
                SELECT sa.supervisor_id, sa.student_id
                FROM student_assignments sa
            ) assignments
            WHERE supervisor_id IS NOT NULL
            GROUP BY supervisor_id
            """
        ).fetchall()
    finally:
        conn.close()

    supervisors = {}
    for row in supervisor_rows:
        supervisor_id = int(_value(row, "id", 0, 0) or 0)
        if not supervisor_id:
            continue
        username = str(_value(row, "username", 1, "") or "")
        profile_picture = str(_value(row, "profile_picture", 5, "") or "").strip()
        supervisors[supervisor_id] = {
            "id": supervisor_id,
            "username": username,
            "email": str(_value(row, "email", 2, "") or ""),
            "display_name": _display_name(_value(row, "first_name", 6, ""), _value(row, "middle_name", 7, ""), _value(row, "last_name", 8, ""), username),
            "employee_id": str(_value(row, "employee_id", 9, "") or ""),
            "job_title": str(_value(row, "job_title", 10, "") or ""),
            "department": str(_value(row, "department", 11, "") or ""),
            "specialization": str(_value(row, "specialization", 12, "") or ""),
            "status": "pending" if _value(row, "role", 3, "") == "pending_supervisor" else str(_value(row, "status", 4, "active") or "active").lower(),
            "profile_picture_url": f"/uploads/profile_pictures/{profile_picture}" if profile_picture else "",
            "classes": [],
            "programs": [],
            "assigned_students": 0,
        }

    class_options = {}
    programs = set()
    departments = set()
    for supervisor in supervisors.values():
        if supervisor["department"]:
            departments.add(supervisor["department"])

    for row in class_rows:
        supervisor = supervisors.get(int(_value(row, "supervisor_id", 0, 0) or 0))
        if not supervisor:
            continue
        class_id = int(_value(row, "class_id", 1, 0) or 0)
        classroom_name = str(_value(row, "classroom_name", 2, "") or "")
        section = str(_value(row, "section", 3, "") or "")
        program = str(_value(row, "program", 5, "") or "")
        class_info = {
            "id": class_id,
            "name": classroom_name,
            "section": section,
            "label": _class_label(classroom_name, section),
            "classroom_type": str(_value(row, "classroom_type", 4, "classroom") or "classroom"),
            "program": program,
            "student_count": int(_value(row, "student_count", 6, 0) or 0),
        }
        supervisor["classes"].append(class_info)
        class_options[class_id] = {"id": class_id, "label": class_info["label"]}
        if program and program not in supervisor["programs"]:
            supervisor["programs"].append(program)
            programs.add(program)

    for row in assigned_rows:
        supervisor = supervisors.get(int(_value(row, "supervisor_id", 0, 0) or 0))
        if supervisor:
            supervisor["assigned_students"] = int(_value(row, "assigned_students", 1, 0) or 0)

    result_supervisors = list(supervisors.values())
    for supervisor in result_supervisors:
        supervisor["classes"].sort(key=lambda item: (item["label"].lower(), item["id"]))
        supervisor["programs"].sort(key=str.casefold)
        supervisor["primary_class"] = supervisor["classes"][0] if supervisor["classes"] else None
        supervisor["primary_program"] = supervisor["programs"][0] if supervisor["programs"] else ""

    return {
        "supervisors": result_supervisors,
        "classes": sorted(class_options.values(), key=lambda item: item["label"].lower()),
        "programs": sorted(programs, key=str.casefold),
        "departments": sorted(departments, key=str.casefold),
    }
