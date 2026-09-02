from flask import Blueprint, abort, render_template, session
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.performance_report_service import build_student_report

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
