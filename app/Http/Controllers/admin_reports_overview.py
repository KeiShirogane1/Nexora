from flask import Blueprint, abort, render_template, session
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.performance_report_service import build_student_report

admin_reports_overview = Blueprint("admin_reports_overview", __name__)

@admin_reports_overview.route("/admin/reports/student/<int:student_id>/overview")
@role_required("admin")
def overview(student_id):
    conn=get_db_connection()
    try:
        student=conn.execute("SELECT id,username,email FROM users WHERE id=? AND role='student'",(student_id,)).fetchone()
        if not student: abort(404)
        attendance=conn.execute("SELECT clock_in,clock_out,hours_rendered,status FROM attendance WHERE student_id=? ORDER BY clock_in DESC",(student_id,)).fetchall()
        total_hours=sum(float((r[2] if len(r)>2 else 0) or 0) for r in attendance)
        sessions=len(attendance); completed=sum(1 for r in attendance if (r[3] if len(r)>3 else '')=='Completed')
        feedback=conn.execute("SELECT comment,created_at,performance_label,users.username AS supervisor FROM feedback JOIN users ON users.id=feedback.supervisor_id WHERE feedback.student_id=? ORDER BY feedback.created_at DESC LIMIT 10",(student_id,)).fetchall()
    finally: conn.close()
    report=build_student_report(student_id,0)
    return render_template("admin/reports/student_overview.html",student=student,report=report,attendance=attendance,feedback=feedback,total_hours=total_hours,sessions=sessions,completed_sessions=completed,active_page="reports")
