from flask import Blueprint, abort, render_template, session
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.performance_report_service import build_student_report
from app.Services.supervisor_profile_service import get_or_create_supervisor_profile

student_classmates = Blueprint("student_classmates", __name__)


def _member(conn, class_id, student_id):
    return conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id=? AND student_id=?", (class_id, student_id)).fetchone()


def _profile(conn, student_id):
    return conn.execute("""SELECT u.id,u.username,u.email,p.first_name,p.middle_name,p.last_name,p.profile_picture,p.student_id,p.grade_year,p.major_program,p.phone_number,p.home_address
        FROM users u LEFT JOIN student_profiles p ON p.user_id=u.id WHERE u.id=? AND u.role='student'""", (student_id,)).fetchone()


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
    viewer_id=session["user_id"]
    conn=get_db_connection()
    try:
        if not _member(conn,class_id,viewer_id) or not _member(conn,class_id,student_id): abort(404)
        profile=_profile(conn,student_id)
        classroom=conn.execute("SELECT id,name,section FROM classrooms WHERE id=?",(class_id,)).fetchone()
    finally: conn.close()
    if not profile or not classroom: abort(404)
    report=build_student_report(student_id,class_id)
    return render_template("classroom/student_classmate_insights.html", profile=profile, classroom=classroom, report=report, active_page="classes")


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
