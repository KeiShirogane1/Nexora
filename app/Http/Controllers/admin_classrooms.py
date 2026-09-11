from datetime import datetime

from flask import Blueprint, abort, render_template, request

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection


admin_classrooms = Blueprint("admin_classrooms", __name__)


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


def _format_date(value):
    if not value:
        return "—"
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return str(value)
    return parsed.strftime("%b %d, %Y").replace(" 0", " ")


def _classroom_dict(row):
    return {
        "id": int(_value(row, "id", 0, 0) or 0),
        "name": _value(row, "name", 1, "") or "",
        "section": _value(row, "section", 2, "") or "",
        "code": _value(row, "code", 3, "") or "",
        "classroom_type": _value(row, "classroom_type", 4, "classroom") or "classroom",
        "archived": bool(int(_value(row, "archived", 5, 0) or 0)),
        "created_at": _format_date(_value(row, "created_at", 6, None)),
        "supervisor_name": _value(row, "supervisor_name", 7, "") or "Unknown Supervisor",
        "company_name": _value(row, "company_name", 8, "") or "",
        "internship_title": _value(row, "internship_title", 9, "") or "",
        "student_count": int(_value(row, "student_count", 10, 0) or 0),
        "classwork_count": int(_value(row, "classwork_count", 11, 0) or 0),
    }


@admin_classrooms.route("/admin/classrooms")
@role_required("admin")
def classrooms():
    search = (request.args.get("search") or "").strip()
    classroom_type = (request.args.get("type") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()

    if classroom_type not in {"all", "classroom", "internship"}:
        classroom_type = "all"
    if status not in {"all", "active", "archived"}:
        status = "all"

    filters = ["1 = 1"]
    params = []

    if classroom_type in {"classroom", "internship"}:
        filters.append("COALESCE(c.classroom_type, 'classroom') = ?")
        params.append(classroom_type)

    if status == "active":
        filters.append("COALESCE(c.archived, 0) = 0")
    elif status == "archived":
        filters.append("COALESCE(c.archived, 0) = 1")

    if search:
        term = f"%{search}%"
        filters.append(
            """(
                LOWER(c.name) LIKE LOWER(?)
                OR LOWER(c.section) LIKE LOWER(?)
                OR LOWER(supervisor.username) LIKE LOWER(?)
                OR LOWER(COALESCE(cid.company_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(cid.internship_title, '')) LIKE LOWER(?)
            )"""
        )
        params.extend([term, term, term, term, term])

    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT
                c.id,
                c.name,
                c.section,
                c.code,
                COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                COALESCE(c.archived, 0) AS archived,
                c.created_at,
                supervisor.username AS supervisor_name,
                COALESCE(cid.company_name, '') AS company_name,
                COALESCE(cid.internship_title, '') AS internship_title,
                (
                    SELECT COUNT(*)
                    FROM classroom_students cs
                    WHERE cs.classroom_id = c.id
                ) AS student_count,
                (
                    SELECT COUNT(*)
                    FROM classroom_assignments ca
                    WHERE ca.classroom_id = c.id
                ) AS classwork_count
            FROM classrooms c
            JOIN users supervisor
              ON supervisor.id = c.supervisor_id
            LEFT JOIN classroom_internship_details cid
              ON cid.classroom_id = c.id
            WHERE {' AND '.join(filters)}
            ORDER BY
                COALESCE(c.archived, 0) ASC,
                c.created_at DESC,
                c.id DESC
            """,
            tuple(params),
        ).fetchall()

        summary_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN COALESCE(archived, 0) = 0 THEN 1 ELSE 0 END) AS active_count,
                SUM(CASE WHEN COALESCE(classroom_type, 'classroom') = 'internship' THEN 1 ELSE 0 END) AS internship_count,
                SUM(CASE WHEN COALESCE(archived, 0) = 1 THEN 1 ELSE 0 END) AS archived_count
            FROM classrooms
            """
        ).fetchone()
    finally:
        conn.close()

    classroom_rows = [_classroom_dict(row) for row in rows]
    summary = {
        "total": int(_value(summary_row, "total_count", 0, 0) or 0),
        "active": int(_value(summary_row, "active_count", 1, 0) or 0),
        "internship": int(_value(summary_row, "internship_count", 2, 0) or 0),
        "archived": int(_value(summary_row, "archived_count", 3, 0) or 0),
    }

    return render_template(
        "admin/classrooms.html",
        classrooms=classroom_rows,
        summary=summary,
        search=search,
        classroom_type=classroom_type,
        status=status,
        active_page="classrooms",
    )


@admin_classrooms.route("/admin/classrooms/<int:classroom_id>")
@role_required("admin")
def classroom_detail(classroom_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT
                c.id,
                c.name,
                c.section,
                c.description,
                c.code,
                COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                COALESCE(c.archived, 0) AS archived,
                c.created_at,
                supervisor.id AS supervisor_id,
                supervisor.username AS supervisor_name,
                supervisor.email AS supervisor_email,
                COALESCE(cid.internship_title, '') AS internship_title,
                COALESCE(cid.company_name, '') AS company_name,
                COALESCE(cid.industry, '') AS industry,
                COALESCE(cid.work_arrangement, '') AS work_arrangement,
                COALESCE(cid.schedule_type, '') AS schedule_type,
                COALESCE(cid.hours_mode, '') AS hours_mode,
                COALESCE(cid.compensation, '') AS compensation,
                COALESCE(cid.location, '') AS location,
                COALESCE(cid.start_date, '') AS start_date,
                COALESCE(cid.end_date, '') AS end_date,
                COALESCE(cid.enrollment_deadline, '') AS enrollment_deadline,
                COALESCE(cid.required_hours, 0) AS required_hours,
                COALESCE(cid.company_website, '') AS company_website,
                COALESCE(cid.company_description, '') AS company_description,
                COALESCE(cid.internship_description, '') AS internship_description
            FROM classrooms c
            JOIN users supervisor
              ON supervisor.id = c.supervisor_id
            LEFT JOIN classroom_internship_details cid
              ON cid.classroom_id = c.id
            WHERE c.id = ?
            LIMIT 1
            """,
            (classroom_id,),
        ).fetchone()

        if not row:
            abort(404)

        student_rows = conn.execute(
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
                cs.joined_at
            FROM classroom_students cs
            JOIN users u
              ON u.id = cs.student_id
            LEFT JOIN student_profiles sp
              ON sp.user_id = u.id
            WHERE cs.classroom_id = ?
            ORDER BY cs.joined_at DESC, u.username ASC
            """,
            (classroom_id,),
        ).fetchall()

        classwork_count = conn.execute(
            "SELECT COUNT(*) FROM classroom_assignments WHERE classroom_id = ?",
            (classroom_id,),
        ).fetchone()[0]

        post_count = conn.execute(
            "SELECT COUNT(*) FROM classroom_posts WHERE classroom_id = ?",
            (classroom_id,),
        ).fetchone()[0]

        responsibilities = []
        qualifications = []
        classroom_type = _value(row, "classroom_type", 5, "classroom") or "classroom"
        if classroom_type == "internship":
            responsibilities = [
                item[0]
                for item in conn.execute(
                    """
                    SELECT responsibility
                    FROM classroom_internship_responsibilities
                    WHERE classroom_id = ?
                    ORDER BY sort_order ASC, id ASC
                    """,
                    (classroom_id,),
                ).fetchall()
            ]
            qualifications = [
                item[0]
                for item in conn.execute(
                    """
                    SELECT qualification
                    FROM classroom_internship_qualifications
                    WHERE classroom_id = ?
                    ORDER BY sort_order ASC, id ASC
                    """,
                    (classroom_id,),
                ).fetchall()
            ]
    finally:
        conn.close()

    classroom = {
        "id": int(_value(row, "id", 0, 0) or 0),
        "name": _value(row, "name", 1, "") or "",
        "section": _value(row, "section", 2, "") or "",
        "description": _value(row, "description", 3, "") or "",
        "code": _value(row, "code", 4, "") or "",
        "classroom_type": _value(row, "classroom_type", 5, "classroom") or "classroom",
        "archived": bool(int(_value(row, "archived", 6, 0) or 0)),
        "created_at": _format_date(_value(row, "created_at", 7, None)),
        "supervisor_id": int(_value(row, "supervisor_id", 8, 0) or 0),
        "supervisor_name": _value(row, "supervisor_name", 9, "") or "Unknown Supervisor",
        "supervisor_email": _value(row, "supervisor_email", 10, "") or "",
        "internship_title": _value(row, "internship_title", 11, "") or "",
        "company_name": _value(row, "company_name", 12, "") or "",
        "industry": _value(row, "industry", 13, "") or "",
        "work_arrangement": _value(row, "work_arrangement", 14, "") or "",
        "schedule_type": _value(row, "schedule_type", 15, "") or "",
        "hours_mode": _value(row, "hours_mode", 16, "") or "",
        "compensation": _value(row, "compensation", 17, "") or "",
        "location": _value(row, "location", 18, "") or "",
        "start_date": _value(row, "start_date", 19, "") or "",
        "end_date": _value(row, "end_date", 20, "") or "",
        "enrollment_deadline": _value(row, "enrollment_deadline", 21, "") or "",
        "required_hours": int(_value(row, "required_hours", 22, 0) or 0),
        "company_website": _value(row, "company_website", 23, "") or "",
        "company_description": _value(row, "company_description", 24, "") or "",
        "internship_description": _value(row, "internship_description", 25, "") or "",
    }

    students = []
    for student_row in student_rows:
        first_name = _value(student_row, "first_name", 3, "") or ""
        middle_name = _value(student_row, "middle_name", 4, "") or ""
        last_name = _value(student_row, "last_name", 5, "") or ""
        username = _value(student_row, "username", 1, "") or ""
        full_name = " ".join(
            part for part in (first_name, middle_name, last_name) if part
        ) or username
        students.append(
            {
                "id": int(_value(student_row, "id", 0, 0) or 0),
                "username": username,
                "email": _value(student_row, "email", 2, "") or "",
                "display_name": full_name,
                "student_number": _value(student_row, "student_number", 6, "") or "",
                "major_program": _value(student_row, "major_program", 7, "") or "",
                "joined_at": _format_date(_value(student_row, "joined_at", 8, None)),
            }
        )

    return render_template(
        "admin/classroom_detail.html",
        classroom=classroom,
        students=students,
        classwork_count=int(classwork_count or 0),
        post_count=int(post_count or 0),
        responsibilities=responsibilities,
        qualifications=qualifications,
        active_page="classrooms",
    )
