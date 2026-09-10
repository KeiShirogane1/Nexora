from flask import Blueprint, abort, render_template, request, session

from app.Http.Middleware.security import role_required
from app.Services.daily_performance_history_service import (
    get_supervisor_daily_performance_history,
)


daily_performance_history = Blueprint("daily_performance_history", __name__)


@daily_performance_history.route("/supervisor/classes/<int:class_id>/daily-performance")
@role_required("supervisor")
def supervisor_history(class_id):
    student_id = request.args.get("student_id", type=int)
    context = get_supervisor_daily_performance_history(
        supervisor_id=session["user_id"],
        classroom_id=class_id,
        student_id=student_id,
    )
    if not context.get("ok"):
        abort(int(context.get("status_code") or 404))

    return render_template(
        "classroom/supervisor_daily_performance_history.html",
        classroom=context["classroom"],
        roster=context["roster"],
        selected_student=context["selected_student"],
        history=context["history"],
        summary=context["summary"],
        active_page="classes",
    )
