from flask import Blueprint, abort, render_template, session

from app.Http.Middleware.security import role_required
from app.Services.intern_profile_service import get_supervisor_intern_profile
from app.Services.ojt_evaluation_service import get_supervisor_evaluation_context


intern_profile = Blueprint("intern_profile", __name__)


@intern_profile.route("/supervisor/classes/<int:class_id>/interns/<int:student_id>")
@role_required("supervisor")
def supervisor_intern_profile(class_id, student_id):
    context = get_supervisor_intern_profile(
        supervisor_id=session["user_id"],
        classroom_id=class_id,
        student_id=student_id,
    )
    if not context.get("ok"):
        abort(int(context.get("status_code") or 404))

    evaluation_context = get_supervisor_evaluation_context(
        supervisor_id=session["user_id"],
        classroom_id=class_id,
        student_id=student_id,
    )
    if not evaluation_context.get("ok"):
        abort(int(evaluation_context.get("status_code") or 404))

    return render_template(
        "classroom/supervisor_intern_profile.html",
        classroom=context["classroom"],
        student=context["student"],
        attendance=context["attendance"],
        attendance_summary=context["attendance_summary"],
        daily_performance=context["daily_performance"],
        logbook_entries=context["logbook_entries"],
        logbook_summary=context["logbook_summary"],
        work_items=context["work_items"],
        work_summary=context["work_summary"],
        official_evaluation=evaluation_context.get("evaluation"),
        active_page="classes",
    )
