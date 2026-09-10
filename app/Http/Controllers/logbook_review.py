from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

from app.Http.Middleware.security import role_required
from app.Services.logbook_photo_service import get_logbook_photos
from app.Services.logbook_review_service import (
    get_student_review_page,
    get_supervisor_logbook_context,
    get_supervisor_logbook_photo,
    revise_daily_log,
    save_supervisor_review,
)
from app.Services.notification_service import create_notification


logbook_review = Blueprint("logbook_review", __name__)


@logbook_review.route("/supervisor/classes/<int:class_id>/logbook")
@role_required("supervisor")
def supervisor_logbook(class_id):
    selected_log_id = request.args.get("log_id", type=int)
    context = get_supervisor_logbook_context(
        supervisor_id=session["user_id"],
        classroom_id=class_id,
        selected_log_id=selected_log_id,
    )
    if not context.get("ok"):
        abort(int(context.get("status_code") or 404))
    return render_template(
        "classroom/supervisor_logbook_review.html",
        classroom=context["classroom"],
        entries=context["entries"],
        selected_entry=context["selected_entry"],
        selected_photos=context["selected_photos"],
        summary=context["summary"],
        active_page="classes",
    )


@logbook_review.route(
    "/supervisor/classes/<int:class_id>/logbook/<int:log_id>/review",
    methods=["POST"],
)
@role_required("supervisor")
def review_daily_log(class_id, log_id):
    try:
        result = save_supervisor_review(
            supervisor_id=session["user_id"],
            classroom_id=class_id,
            log_id=log_id,
            status=request.form.get("status"),
            comments=request.form.get("comments"),
        )
    except Exception as exc:
        print("daily logbook review failed:", exc)
        result = {"ok": False, "error": "Unable to save the Daily OJT review."}

    if result.get("ok"):
        flash(f"Daily OJT entry marked {result['status_label']}.", "success")
        try:
            create_notification(
                int(result["student_id"]),
                "Daily OJT Logbook Review",
                f"Your Daily OJT entry was marked {result['status_label']}.",
                "feedback",
                link_url=url_for("logbook_review.student_review", log_id=log_id),
            )
        except Exception as exc:
            print("daily logbook review notification failed:", exc)
    else:
        flash(result.get("error") or "Unable to save the Daily OJT review.", "danger")

    return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id, log_id=log_id))


@logbook_review.route("/supervisor/classes/<int:class_id>/logbook/photo/<int:photo_id>")
@role_required("supervisor")
def supervisor_photo(class_id, photo_id):
    photo = get_supervisor_logbook_photo(session["user_id"], class_id, photo_id)
    if not photo:
        abort(404)
    return send_file(
        photo["path"],
        mimetype=photo["mime_type"],
        as_attachment=False,
        download_name=photo["original_filename"],
        conditional=True,
    )


@logbook_review.route("/student/daily-log/<int:log_id>/review")
@role_required("student")
def student_review(log_id):
    entry = get_student_review_page(session["user_id"], log_id)
    if not entry:
        abort(404)
    return render_template(
        "student/logbook_review.html",
        entry=entry,
        photos=get_logbook_photos(session["user_id"], log_id),
        active_page="logbook",
    )


@logbook_review.route("/student/daily-log/<int:log_id>/revise", methods=["POST"])
@role_required("student")
def student_revise(log_id):
    try:
        result = revise_daily_log(
            student_id=session["user_id"],
            log_id=log_id,
            accomplishment=request.form.get("accomplishment"),
            reflection=request.form.get("reflection"),
            challenges=request.form.get("challenges"),
        )
    except Exception as exc:
        print("daily logbook revision failed:", exc)
        result = {"ok": False, "error": "Unable to submit the Daily OJT revision."}

    if result.get("ok"):
        flash("Daily OJT revision submitted for supervisor review.", "success")
        try:
            create_notification(
                int(result["supervisor_id"]),
                "Daily OJT Revision Submitted",
                "An intern revised a Daily OJT entry that you returned for changes.",
                "feedback",
                link_url=url_for(
                    "logbook_review.supervisor_logbook",
                    class_id=int(result["classroom_id"]),
                    log_id=log_id,
                ),
            )
        except Exception as exc:
            print("daily logbook revision notification failed:", exc)
    else:
        flash(result.get("error") or "Unable to submit the Daily OJT revision.", "danger")

    return redirect(url_for("logbook_review.student_review", log_id=log_id))
