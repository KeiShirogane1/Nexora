import os
from datetime import datetime

from flask import Blueprint, abort, current_app, render_template, request, send_file

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


def _format_datetime(value):
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


def _student_display_name(first_name, middle_name, last_name, username):
    parts = [part for part in (first_name, middle_name, last_name) if part]
    return " ".join(parts) if parts else (username or "Student")


def _document_display_name(filename, student_id):
    filename = filename or "Document"
    prefix = f"{student_id}_"
    if filename.startswith(prefix):
        return filename[len(prefix):]
    return filename


def _format_file_size(size):
    if size is None:
        return "—"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _is_safe_upload_path(filepath):
    upload_base = current_app.config.get("UPLOAD_FOLDER", "")
    if not upload_base or not filepath:
        return False
    try:
        base = os.path.realpath(upload_base)
        candidate = os.path.realpath(filepath)
        return os.path.commonpath([base, candidate]) == base
    except (OSError, ValueError, TypeError):
        return False


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


@admin_classrooms.route("/admin/student-documents")
@role_required("admin")
def student_documents():
    search = (request.args.get("search") or "").strip().lower()
    classroom_type = (request.args.get("type") or "all").strip().lower()
    document_state = (request.args.get("documents") or "all").strip().lower()

    if classroom_type not in {"all", "classroom", "internship"}:
        classroom_type = "all"
    if document_state not in {"all", "with", "without"}:
        document_state = "all"

    conn = get_db_connection()
    try:
        summary_row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM users WHERE role = 'student') AS total_students,
                (
                    SELECT COUNT(DISTINCT d.student_id)
                    FROM documents d
                    JOIN users u ON u.id = d.student_id
                    WHERE u.role = 'student'
                ) AS students_with_documents,
                (SELECT COUNT(*) FROM documents) AS total_documents,
                (SELECT COUNT(*) FROM classrooms) AS total_classrooms
            """
        ).fetchone()

        placement_rows = conn.execute(
            """
            SELECT
                c.id AS classroom_id,
                c.name AS classroom_name,
                c.section,
                COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                COALESCE(c.archived, 0) AS archived,
                supervisor.username AS supervisor_username,
                COALESCE(sup_profile.first_name, '') AS supervisor_first_name,
                COALESCE(sup_profile.last_name, '') AS supervisor_last_name,
                COALESCE(cid.company_name, '') AS company_name,
                COALESCE(cid.internship_title, '') AS internship_title,
                student.id AS student_id,
                student.username,
                student.email,
                COALESCE(sp.first_name, '') AS first_name,
                COALESCE(sp.middle_name, '') AS middle_name,
                COALESCE(sp.last_name, '') AS last_name,
                COALESCE(sp.student_id, '') AS student_number,
                COALESCE(sp.major_program, '') AS major_program,
                COALESCE(sp.grade_year, '') AS grade_year,
                (
                    SELECT COUNT(*)
                    FROM documents d
                    WHERE d.student_id = student.id
                ) AS document_count,
                (
                    SELECT MAX(d.uploaded_at)
                    FROM documents d
                    WHERE d.student_id = student.id
                ) AS last_upload
            FROM classroom_students cs
            JOIN classrooms c ON c.id = cs.classroom_id
            JOIN users student ON student.id = cs.student_id
            JOIN users supervisor ON supervisor.id = c.supervisor_id
            LEFT JOIN student_profiles sp ON sp.user_id = student.id
            LEFT JOIN supervisor_profiles sup_profile ON sup_profile.user_id = supervisor.id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE student.role = 'student'
            ORDER BY
                COALESCE(c.archived, 0) ASC,
                c.created_at DESC,
                c.id DESC,
                COALESCE(sp.last_name, '') ASC,
                COALESCE(sp.first_name, '') ASC,
                student.username ASC
            """
        ).fetchall()

        unassigned_rows = conn.execute(
            """
            SELECT
                student.id AS student_id,
                student.username,
                student.email,
                COALESCE(sp.first_name, '') AS first_name,
                COALESCE(sp.middle_name, '') AS middle_name,
                COALESCE(sp.last_name, '') AS last_name,
                COALESCE(sp.student_id, '') AS student_number,
                COALESCE(sp.major_program, '') AS major_program,
                COALESCE(sp.grade_year, '') AS grade_year,
                (
                    SELECT COUNT(*)
                    FROM documents d
                    WHERE d.student_id = student.id
                ) AS document_count,
                (
                    SELECT MAX(d.uploaded_at)
                    FROM documents d
                    WHERE d.student_id = student.id
                ) AS last_upload
            FROM users student
            LEFT JOIN student_profiles sp ON sp.user_id = student.id
            WHERE student.role = 'student'
              AND NOT EXISTS (
                  SELECT 1
                  FROM classroom_students cs
                  WHERE cs.student_id = student.id
              )
            ORDER BY
                COALESCE(sp.last_name, '') ASC,
                COALESCE(sp.first_name, '') ASC,
                student.username ASC
            """
        ).fetchall()

        latest_rows = conn.execute(
            """
            SELECT
                d.id AS document_id,
                d.student_id,
                d.filename,
                d.uploaded_at,
                student.username,
                COALESCE(sp.first_name, '') AS first_name,
                COALESCE(sp.middle_name, '') AS middle_name,
                COALESCE(sp.last_name, '') AS last_name,
                COALESCE(sp.student_id, '') AS student_number,
                COALESCE(sp.major_program, '') AS major_program
            FROM documents d
            JOIN users student ON student.id = d.student_id
            LEFT JOIN student_profiles sp ON sp.user_id = student.id
            WHERE student.role = 'student'
            ORDER BY d.uploaded_at DESC, d.id DESC
            LIMIT 8
            """
        ).fetchall()
    finally:
        conn.close()

    def student_from_row(row, offset=10):
        if offset == 10:
            student_id = int(_value(row, "student_id", 10, 0) or 0)
            username = _value(row, "username", 11, "") or ""
            email = _value(row, "email", 12, "") or ""
            first_name = _value(row, "first_name", 13, "") or ""
            middle_name = _value(row, "middle_name", 14, "") or ""
            last_name = _value(row, "last_name", 15, "") or ""
            student_number = _value(row, "student_number", 16, "") or ""
            major_program = _value(row, "major_program", 17, "") or ""
            grade_year = _value(row, "grade_year", 18, "") or ""
            document_count = int(_value(row, "document_count", 19, 0) or 0)
            last_upload_raw = _value(row, "last_upload", 20, None)
        else:
            student_id = int(_value(row, "student_id", 0, 0) or 0)
            username = _value(row, "username", 1, "") or ""
            email = _value(row, "email", 2, "") or ""
            first_name = _value(row, "first_name", 3, "") or ""
            middle_name = _value(row, "middle_name", 4, "") or ""
            last_name = _value(row, "last_name", 5, "") or ""
            student_number = _value(row, "student_number", 6, "") or ""
            major_program = _value(row, "major_program", 7, "") or ""
            grade_year = _value(row, "grade_year", 8, "") or ""
            document_count = int(_value(row, "document_count", 9, 0) or 0)
            last_upload_raw = _value(row, "last_upload", 10, None)

        display_name = _student_display_name(first_name, middle_name, last_name, username)
        return {
            "id": student_id,
            "username": username,
            "email": email,
            "display_name": display_name,
            "student_number": student_number,
            "major_program": major_program,
            "grade_year": grade_year,
            "document_count": document_count,
            "last_upload": _format_datetime(last_upload_raw),
            "last_upload_raw": str(last_upload_raw or ""),
        }

    def passes_student_filters(student, classroom_search_text=""):
        if document_state == "with" and student["document_count"] <= 0:
            return False
        if document_state == "without" and student["document_count"] > 0:
            return False
        if search:
            searchable = " ".join(
                [
                    student["display_name"],
                    student["username"],
                    student["email"],
                    student["student_number"],
                    student["major_program"],
                    student["grade_year"],
                    classroom_search_text,
                ]
            ).lower()
            if search not in searchable:
                return False
        return True

    grouped = {}
    classroom_order = []

    for row in placement_rows:
        row_type = (_value(row, "classroom_type", 3, "classroom") or "classroom").lower()
        if classroom_type != "all" and row_type != classroom_type:
            continue

        classroom_id = int(_value(row, "classroom_id", 0, 0) or 0)
        supervisor_username = _value(row, "supervisor_username", 5, "") or "Unknown Supervisor"
        supervisor_name = _student_display_name(
            _value(row, "supervisor_first_name", 6, "") or "",
            "",
            _value(row, "supervisor_last_name", 7, "") or "",
            supervisor_username,
        )
        classroom = grouped.get(classroom_id)
        if classroom is None:
            classroom = {
                "id": classroom_id,
                "name": _value(row, "classroom_name", 1, "") or "Classroom",
                "section": _value(row, "section", 2, "") or "",
                "classroom_type": row_type,
                "archived": bool(int(_value(row, "archived", 4, 0) or 0)),
                "supervisor_name": supervisor_name,
                "company_name": _value(row, "company_name", 8, "") or "",
                "internship_title": _value(row, "internship_title", 9, "") or "",
                "students": [],
            }
            grouped[classroom_id] = classroom
            classroom_order.append(classroom_id)

        student = student_from_row(row, offset=10)
        classroom_search_text = " ".join(
            [
                classroom["name"],
                classroom["section"],
                classroom["supervisor_name"],
                classroom["company_name"],
                classroom["internship_title"],
            ]
        )
        if passes_student_filters(student, classroom_search_text):
            classroom["students"].append(student)

    classroom_groups = [
        grouped[classroom_id]
        for classroom_id in classroom_order
        if grouped[classroom_id]["students"]
    ]

    unassigned_students = []
    if classroom_type == "all":
        for row in unassigned_rows:
            student = student_from_row(row, offset=0)
            if passes_student_filters(student, "Not enrolled in a classroom"):
                unassigned_students.append(student)

    latest_uploads = []
    for row in latest_rows:
        student_id = int(_value(row, "student_id", 1, 0) or 0)
        username = _value(row, "username", 4, "") or ""
        display_name = _student_display_name(
            _value(row, "first_name", 5, "") or "",
            _value(row, "middle_name", 6, "") or "",
            _value(row, "last_name", 7, "") or "",
            username,
        )
        filename = _value(row, "filename", 2, "") or "Document"
        latest_uploads.append(
            {
                "document_id": int(_value(row, "document_id", 0, 0) or 0),
                "student_id": student_id,
                "student_name": display_name,
                "student_number": _value(row, "student_number", 8, "") or "",
                "major_program": _value(row, "major_program", 9, "") or "",
                "filename": _document_display_name(filename, student_id),
                "uploaded_at": _format_datetime(_value(row, "uploaded_at", 3, None)),
            }
        )

    summary = {
        "total_students": int(_value(summary_row, "total_students", 0, 0) or 0),
        "with_documents": int(_value(summary_row, "students_with_documents", 1, 0) or 0),
        "total_documents": int(_value(summary_row, "total_documents", 2, 0) or 0),
        "total_classrooms": int(_value(summary_row, "total_classrooms", 3, 0) or 0),
    }

    shown_students = sum(len(group["students"]) for group in classroom_groups) + len(unassigned_students)

    return render_template(
        "admin/student_documents.html",
        classroom_groups=classroom_groups,
        unassigned_students=unassigned_students,
        latest_uploads=latest_uploads,
        summary=summary,
        shown_students=shown_students,
        search=request.args.get("search", ""),
        classroom_type=classroom_type,
        document_state=document_state,
        active_page="student_documents",
    )


@admin_classrooms.route("/admin/student-documents/<int:student_id>")
@role_required("admin")
def student_document_folder(student_id):
    conn = get_db_connection()
    try:
        student_row = conn.execute(
            """
            SELECT
                u.id,
                u.username,
                u.email,
                u.status,
                COALESCE(sp.first_name, '') AS first_name,
                COALESCE(sp.middle_name, '') AS middle_name,
                COALESCE(sp.last_name, '') AS last_name,
                COALESCE(sp.student_id, '') AS student_number,
                COALESCE(sp.major_program, '') AS major_program,
                COALESCE(sp.grade_year, '') AS grade_year
            FROM users u
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE u.id = ? AND u.role = 'student'
            LIMIT 1
            """,
            (student_id,),
        ).fetchone()

        if not student_row:
            abort(404)

        document_rows = conn.execute(
            """
            SELECT id, filename, filepath, uploaded_at
            FROM documents
            WHERE student_id = ?
            ORDER BY uploaded_at DESC, id DESC
            """,
            (student_id,),
        ).fetchall()

        membership_rows = conn.execute(
            """
            SELECT
                c.id,
                c.name,
                c.section,
                COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                COALESCE(c.archived, 0) AS archived,
                supervisor.username AS supervisor_username,
                COALESCE(sup_profile.first_name, '') AS supervisor_first_name,
                COALESCE(sup_profile.last_name, '') AS supervisor_last_name,
                COALESCE(cid.company_name, '') AS company_name,
                COALESCE(cid.internship_title, '') AS internship_title
            FROM classroom_students cs
            JOIN classrooms c ON c.id = cs.classroom_id
            JOIN users supervisor ON supervisor.id = c.supervisor_id
            LEFT JOIN supervisor_profiles sup_profile ON sup_profile.user_id = supervisor.id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE cs.student_id = ?
            ORDER BY COALESCE(c.archived, 0) ASC, c.created_at DESC, c.id DESC
            """,
            (student_id,),
        ).fetchall()
    finally:
        conn.close()

    username = _value(student_row, "username", 1, "") or ""
    student = {
        "id": int(_value(student_row, "id", 0, 0) or 0),
        "username": username,
        "email": _value(student_row, "email", 2, "") or "",
        "status": _value(student_row, "status", 3, "active") or "active",
        "display_name": _student_display_name(
            _value(student_row, "first_name", 4, "") or "",
            _value(student_row, "middle_name", 5, "") or "",
            _value(student_row, "last_name", 6, "") or "",
            username,
        ),
        "student_number": _value(student_row, "student_number", 7, "") or "",
        "major_program": _value(student_row, "major_program", 8, "") or "",
        "grade_year": _value(student_row, "grade_year", 9, "") or "",
    }

    documents = []
    extensions = set()
    latest_upload = None
    for row in document_rows:
        document_id = int(_value(row, "id", 0, 0) or 0)
        filename = _value(row, "filename", 1, "") or "Document"
        filepath = _value(row, "filepath", 2, "") or ""
        display_filename = _document_display_name(filename, student_id)
        extension = os.path.splitext(display_filename)[1].lower().lstrip(".") or "file"
        extensions.add(extension)
        size = None
        available = _is_safe_upload_path(filepath) and os.path.isfile(filepath)
        if available:
            try:
                size = os.path.getsize(filepath)
            except OSError:
                size = None
        uploaded_raw = _value(row, "uploaded_at", 3, None)
        if latest_upload is None:
            latest_upload = _format_datetime(uploaded_raw)
        documents.append(
            {
                "id": document_id,
                "filename": display_filename,
                "extension": extension,
                "size": _format_file_size(size),
                "uploaded_at": _format_datetime(uploaded_raw),
                "available": available,
                "is_image": extension in {"png", "jpg", "jpeg", "gif"},
            }
        )

    memberships = []
    for row in membership_rows:
        supervisor_username = _value(row, "supervisor_username", 5, "") or "Unknown Supervisor"
        memberships.append(
            {
                "id": int(_value(row, "id", 0, 0) or 0),
                "name": _value(row, "name", 1, "") or "Classroom",
                "section": _value(row, "section", 2, "") or "",
                "classroom_type": _value(row, "classroom_type", 3, "classroom") or "classroom",
                "archived": bool(int(_value(row, "archived", 4, 0) or 0)),
                "supervisor_name": _student_display_name(
                    _value(row, "supervisor_first_name", 6, "") or "",
                    "",
                    _value(row, "supervisor_last_name", 7, "") or "",
                    supervisor_username,
                ),
                "company_name": _value(row, "company_name", 8, "") or "",
                "internship_title": _value(row, "internship_title", 9, "") or "",
            }
        )

    return render_template(
        "admin/student_document_folder.html",
        student=student,
        documents=documents,
        memberships=memberships,
        latest_upload=latest_upload or "No uploads yet",
        file_type_count=len(extensions),
        active_page="student_documents",
    )


@admin_classrooms.route(
    "/admin/student-documents/<int:student_id>/document/<int:document_id>"
)
@role_required("admin")
def view_student_document(student_id, document_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT filename, filepath
            FROM documents
            WHERE id = ? AND student_id = ?
            LIMIT 1
            """,
            (document_id, student_id),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)

    filename = _value(row, "filename", 0, "") or "Document"
    filepath = _value(row, "filepath", 1, "") or ""
    if not _is_safe_upload_path(filepath):
        abort(403)
    if not os.path.isfile(filepath):
        abort(404)

    return send_file(
        filepath,
        as_attachment=False,
        download_name=_document_display_name(filename, student_id),
    )
