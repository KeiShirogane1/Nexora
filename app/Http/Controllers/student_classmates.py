from flask import Blueprint, abort, jsonify, render_template, session
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.supervisor_profile_service import get_or_create_supervisor_profile

student_classmates = Blueprint("student_classmates", __name__)


def _member(conn, class_id, student_id):
    return conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id=? AND student_id=?", (class_id, student_id)).fetchone()


def _profile(conn, student_id):
    return conn.execute("""SELECT u.id,u.username,u.email,p.first_name,p.middle_name,p.last_name,p.profile_picture,p.student_id,p.grade_year,p.major_program,p.phone_number,p.home_address
        FROM users u LEFT JOIN student_profiles p ON p.user_id=u.id WHERE u.id=? AND u.role='student'""", (student_id,)).fetchone()


def _row_value(row, key, index=0, default=None):
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


@student_classmates.route("/student/classes/<int:class_id>/info")
@role_required("student")
def classroom_info(class_id):
    viewer_id = session["user_id"]
    conn = get_db_connection()
    try:
        if not _member(conn, class_id, viewer_id):
            abort(404)

        classroom = conn.execute(
            """SELECT c.id, c.name, c.section, c.description, c.code, c.archived,
                      c.supervisor_id, u.username AS supervisor_name
               FROM classrooms c
               JOIN users u ON u.id = c.supervisor_id
               WHERE c.id = ?""",
            (class_id,),
        ).fetchone()
        if not classroom:
            abort(404)

        details = conn.execute(
            """SELECT internship_title, company_name, industry, work_arrangement,
                      schedule_type, hours_mode, compensation, location, start_date,
                      end_date, enrollment_deadline, required_hours, company_website,
                      company_description, internship_description
               FROM classroom_internship_details
               WHERE classroom_id = ?""",
            (class_id,),
        ).fetchone()
        responsibility_rows = conn.execute(
            """SELECT responsibility
               FROM classroom_internship_responsibilities
               WHERE classroom_id = ?
               ORDER BY sort_order, id""",
            (class_id,),
        ).fetchall()
        qualification_rows = conn.execute(
            """SELECT qualification
               FROM classroom_internship_qualifications
               WHERE classroom_id = ?
               ORDER BY sort_order, id""",
            (class_id,),
        ).fetchall()
    finally:
        conn.close()

    archived = bool(_row_value(classroom, "archived", 5, 0))
    payload = {
        "id": _row_value(classroom, "id", 0),
        "name": _row_value(classroom, "name", 1, ""),
        "section": _row_value(classroom, "section", 2, ""),
        "description": _row_value(classroom, "description", 3, ""),
        "code": _row_value(classroom, "code", 4, ""),
        "status": "Archived" if archived else "Active",
        "supervisor": _row_value(classroom, "supervisor_name", 7, "Supervisor"),
        "internship_title": _row_value(details, "internship_title", 0, _row_value(classroom, "name", 1, "")),
        "company_name": _row_value(details, "company_name", 1, ""),
        "industry": _row_value(details, "industry", 2, ""),
        "work_arrangement": _row_value(details, "work_arrangement", 3, ""),
        "schedule_type": _row_value(details, "schedule_type", 4, "not_specified"),
        "hours_mode": _row_value(details, "hours_mode", 5, "not_specified"),
        "compensation": _row_value(details, "compensation", 6, "Not Specified"),
        "location": _row_value(details, "location", 7, ""),
        "start_date": _row_value(details, "start_date", 8, ""),
        "end_date": _row_value(details, "end_date", 9, ""),
        "enrollment_deadline": _row_value(details, "enrollment_deadline", 10, ""),
        "required_hours": _row_value(details, "required_hours", 11, 0),
        "company_website": _row_value(details, "company_website", 12, ""),
        "company_description": _row_value(details, "company_description", 13, ""),
        "internship_description": _row_value(details, "internship_description", 14, ""),
        "responsibilities": [
            _row_value(row, "responsibility", 0, "")
            for row in responsibility_rows
            if _row_value(row, "responsibility", 0, "")
        ],
        "qualifications": [
            _row_value(row, "qualification", 0, "")
            for row in qualification_rows
            if _row_value(row, "qualification", 0, "")
        ],
    }
    return jsonify({"ok": True, "classroom": payload})


@student_classmates.route("/student/classes/<int:class_id>/people/<int:student_id>")
@role_required("student")
def classmate_profile(class_id, student_id):
    viewer_id=session["user_id"]
    conn=get_db_connection()
    try:
        if not _member(conn,class_id,viewer_id) or not _member(conn,class_id,student_id): abort(404)
        profile=_profile(conn,student_id)
        if not profile: abort(404)
        classroom=conn.execute("SELECT id,name,section FROM classrooms WHERE id=?",(class_id,)).fetchone()
    finally: conn.close()
    return render_template("classroom/student_classmate_profile.html", profile=profile, classroom=classroom, student_id=student_id, active_page="classes")


@student_classmates.route("/student/classes/<int:class_id>/people/<int:student_id>/insights")
@role_required("student")
def classmate_insights(class_id, student_id):
    # Student ML insights are private. Students use the dedicated own-insights
    # route; peer analytics must never be exposed through a classmate URL.
    abort(404)


@student_classmates.route("/student/classes/<int:class_id>/teacher")
@role_required("student")
def teacher_profile(class_id):
    viewer_id = session["user_id"]
    conn = get_db_connection()
    try:
        if not _member(conn, class_id, viewer_id):
            abort(404)
        classroom = conn.execute(
            "SELECT id,name,section,description,supervisor_id FROM classrooms WHERE id=?",
            (class_id,)
        ).fetchone()
        if not classroom:
            abort(404)
        supervisor_id = classroom["supervisor_id"] if "supervisor_id" in classroom.keys() else classroom[4]
        supervisor = conn.execute(
            "SELECT id,username,email,role,status,profile_picture FROM users WHERE id=? AND role='supervisor' AND status!='inactive'",
            (supervisor_id,)
        ).fetchone()
        if not supervisor:
            abort(404)
    finally:
        conn.close()

    profile = get_or_create_supervisor_profile(supervisor_id)
    profile_data = dict(profile.items()) if hasattr(profile, "items") else {}
    supervisor_data = dict(supervisor.items()) if hasattr(supervisor, "items") else {}
    classroom_data = dict(classroom.items()) if hasattr(classroom, "items") else {}

    return render_template(
        "classroom/student_teacher_profile.html",
        supervisor=supervisor_data,
        profile=profile_data,
        classroom=classroom_data,
        active_page="classes"
    )
