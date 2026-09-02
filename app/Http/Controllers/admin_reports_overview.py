from flask import Blueprint, abort, render_template
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
        total_hours=sum(float((r[2] if len(r)>2 else 0) or 0) for r in attendance); sessions=len(attendance); completed=sum(1 for r in attendance if (r[3] if len(r)>3 else '')=='Completed')
        feedback=conn.execute("SELECT comment,created_at,performance_label,users.username AS supervisor FROM feedback JOIN users ON users.id=feedback.supervisor_id WHERE feedback.student_id=? ORDER BY feedback.created_at DESC LIMIT 10",(student_id,)).fetchall()
        class_rows=conn.execute("SELECT classroom_id FROM classroom_students WHERE student_id=? ORDER BY classroom_id",(student_id,)).fetchall(); class_ids=[r[0] for r in class_rows]
    finally: conn.close()
    reports=[]
    for cid in class_ids:
        try: reports.append(build_student_report(student_id,int(cid)))
        except Exception: pass
    if reports:
        assignments=[a for r in reports for a in r.get("assignments",[])]; graded=[a for a in assignments if a.get("graded") and a.get("percentage") is not None]; percentages=[float(a["percentage"]) for a in graded]
        report=dict(reports[0]); report.update({"assignments":assignments,"graded_count":len(graded),"total_count":len(assignments),"average_percentage":sum(percentages)/len(percentages) if percentages else None,"min_percentage":min(percentages) if percentages else None,"max_percentage":max(percentages) if percentages else None,"completion_rate":len(graded)/len(assignments)*100 if assignments else 0.0})
        if percentages: report["strongest"]=max(graded,key=lambda x:x["percentage"]); report["weakest"]=min(graded,key=lambda x:x["percentage"])
    else:
        report={"performance_label":"Satisfactory","average_percentage":None,"min_percentage":None,"max_percentage":None,"completion_rate":0.0,"graded_count":0,"total_count":0,"assignments":[],"priority":"medium","recommendation":"Continue monitoring performance and completing upcoming internship work.","sentiment":None,"competency":None}
    return render_template("admin/reports/student_overview.html",student=student,report=report,attendance=attendance,feedback=feedback,total_hours=total_hours,sessions=sessions,completed_sessions=completed,active_page="reports")
