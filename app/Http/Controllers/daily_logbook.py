from flask import Blueprint, flash, redirect, request, session, url_for

from app.Http.Middleware.security import role_required
from app.Services.logbook_service import save_daily_log


daily_logbook = Blueprint("daily_logbook", __name__)


@daily_logbook.route("/student/daily-log/save", methods=["POST"])
@role_required("student")
def save_daily_entry():
    result = save_daily_log(
        student_id=session["user_id"],
        attendance_id=request.form.get("attendance_id"),
        accomplishment=request.form.get("accomplishment"),
        reflection=request.form.get("reflection"),
        challenges=request.form.get("challenges"),
        related_assignment_id=request.form.get("related_assignment_id"),
    )

    if result.get("ok"):
        flash("Daily OJT entry saved.", "success")
    else:
        flash(result.get("error") or "Unable to save the Daily OJT entry.", "danger")

    classroom_id = result.get("classroom_id")
    if classroom_id is not None:
        return redirect(url_for("student.logbook", classroom_id=int(classroom_id)))
    return redirect(url_for("student.logbook"))
