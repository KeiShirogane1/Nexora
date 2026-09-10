from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from app.Http.Middleware.security import role_required
from app.Services.ojt_evaluation_service import (
    get_supervisor_evaluation_context,
    reopen_supervisor_ojt_evaluation,
    save_supervisor_ojt_evaluation,
)


ojt_evaluation = Blueprint("ojt_evaluation", __name__)


def _build_items_from_form():
    names = request.form.getlist("criterion_name")
    ratings = request.form.getlist("rating_value")
    maximums = request.form.getlist("max_value")
    weights = request.form.getlist("weight")
    comments = request.form.getlist("item_comments")
    count = max(len(names), len(ratings), len(maximums), len(weights), len(comments), 0)

    items = []
    for index in range(count):
        items.append(
            {
                "criterion_name": names[index] if index < len(names) else "",
                "rating_value": ratings[index] if index < len(ratings) else "",
                "max_value": maximums[index] if index < len(maximums) else "",
                "weight": weights[index] if index < len(weights) else "",
                "comments": comments[index] if index < len(comments) else "",
            }
        )
    return items


@ojt_evaluation.route("/supervisor/classes/<int:class_id>/evaluations", methods=["GET", "POST"])
@role_required("supervisor")
def supervisor_evaluations(class_id):
    supervisor_id = session["user_id"]

    if request.method == "POST":
        student_id = request.form.get("student_id", type=int)
        if not student_id:
            flash("Choose an intern before saving an Official OJT Evaluation.", "danger")
            return redirect(url_for("ojt_evaluation.supervisor_evaluations", class_id=class_id))

        action = (request.form.get("action") or "").strip().lower()
        if action == "reopen":
            result = reopen_supervisor_ojt_evaluation(
                supervisor_id=supervisor_id,
                classroom_id=class_id,
                student_id=student_id,
            )
            if result.get("ok"):
                flash("Official OJT Evaluation reopened as a draft.", "success")
            else:
                flash(result.get("error") or "Unable to reopen evaluation.", "danger")
            return redirect(
                url_for(
                    "ojt_evaluation.supervisor_evaluations",
                    class_id=class_id,
                    student_id=student_id,
                )
            )

        status = "submitted" if action == "submit" else "draft" if action == "save_draft" else None
        if not status:
            flash("Invalid Official OJT Evaluation action.", "danger")
            return redirect(
                url_for(
                    "ojt_evaluation.supervisor_evaluations",
                    class_id=class_id,
                    student_id=student_id,
                )
            )

        result = save_supervisor_ojt_evaluation(
            supervisor_id=supervisor_id,
            classroom_id=class_id,
            student_id=student_id,
            status=status,
            items=_build_items_from_form(),
            overall_score=request.form.get("overall_score"),
            remarks=request.form.get("remarks"),
        )
        if result.get("ok"):
            if status == "submitted":
                flash("Official OJT Evaluation submitted.", "success")
            else:
                flash("Official OJT Evaluation draft saved.", "success")
        else:
            flash(result.get("error") or "Unable to save Official OJT Evaluation.", "danger")

        return redirect(
            url_for(
                "ojt_evaluation.supervisor_evaluations",
                class_id=class_id,
                student_id=student_id,
            )
        )

    requested_student_id = request.args.get("student_id", type=int)
    context = get_supervisor_evaluation_context(
        supervisor_id=supervisor_id,
        classroom_id=class_id,
        student_id=requested_student_id,
    )
    if not context.get("ok"):
        abort(int(context.get("status_code") or 404))

    return render_template(
        "classroom/supervisor_ojt_evaluation.html",
        classroom=context["classroom"],
        students=context["students"],
        selected_student=context["selected_student"],
        evaluation=context["evaluation"],
        evaluation_items=context["items"],
        active_page="classes",
    )
