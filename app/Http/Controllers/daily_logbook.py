from flask import Blueprint, abort, flash, redirect, request, send_file, session, url_for

from app.Http.Middleware.security import role_required
from app.Services.logbook_service import save_daily_log
from app.Services.logbook_photo_service import (
    add_logbook_photos,
    add_photos_for_attendance,
    delete_logbook_photo,
    get_photo_for_student,
)


daily_logbook = Blueprint("daily_logbook", __name__)


@daily_logbook.route("/student/daily-log/save", methods=["POST"])
@role_required("student")
def save_daily_entry():
    attendance_id = request.form.get("attendance_id")
    result = save_daily_log(
        student_id=session["user_id"],
        attendance_id=attendance_id,
        accomplishment=request.form.get("accomplishment"),
        reflection=request.form.get("reflection"),
        challenges=request.form.get("challenges"),
        related_assignment_id=request.form.get("related_assignment_id"),
    )

    if result.get("ok"):
        uploaded = [
            item
            for item in request.files.getlist("photos")
            if item and item.filename
        ]
        if uploaded:
            try:
                photo_result = add_photos_for_attendance(
                    student_id=session["user_id"],
                    attendance_id=attendance_id,
                    files=uploaded,
                )
                if photo_result.get("ok"):
                    added = int(photo_result.get("added") or 0)
                    flash(
                        f"Daily OJT entry saved with {added} photo{'s' if added != 1 else ''}.",
                        "success",
                    )
                else:
                    flash("Daily OJT entry saved.", "success")
                    flash(
                        photo_result.get("error") or "Photo evidence could not be added.",
                        "warning",
                    )
            except Exception as exc:
                print("daily logbook photo upload failed:", exc)
                flash("Daily OJT entry saved.", "success")
                flash("Photo evidence could not be stored.", "warning")
        else:
            flash("Daily OJT entry saved.", "success")
    else:
        flash(result.get("error") or "Unable to save the Daily OJT entry.", "danger")

    classroom_id = result.get("classroom_id")
    if classroom_id is not None:
        return redirect(url_for("student.logbook", classroom_id=int(classroom_id)))
    return redirect(url_for("student.logbook"))


@daily_logbook.route("/student/daily-log/<int:log_id>/photos", methods=["POST"])
@role_required("student")
def add_photos(log_id):
    uploaded = [
        item
        for item in request.files.getlist("photos")
        if item and item.filename
    ]
    if not uploaded:
        flash("Choose at least one photo to upload.", "warning")
        return redirect(url_for("student.logbook"))

    try:
        result = add_logbook_photos(
            student_id=session["user_id"],
            log_id=log_id,
            files=uploaded,
        )
        if result.get("ok"):
            added = int(result.get("added") or 0)
            flash(
                f"Added {added} photo{'s' if added != 1 else ''} to the Daily OJT entry.",
                "success",
            )
        else:
            flash(result.get("error") or "Unable to add photo evidence.", "danger")
    except Exception as exc:
        print("daily logbook photo upload failed:", exc)
        result = {"ok": False}
        flash("Unable to add photo evidence.", "danger")

    attendance_id = result.get("attendance_id")
    if attendance_id:
        return redirect(url_for("student.view_session", attendance_id=int(attendance_id)))
    return redirect(url_for("student.logbook"))


@daily_logbook.route("/student/daily-log/photo/<int:photo_id>")
@role_required("student")
def view_photo(photo_id):
    photo = get_photo_for_student(session["user_id"], photo_id)
    if not photo:
        abort(404)
    return send_file(
        photo["path"],
        mimetype=photo["mime_type"],
        as_attachment=False,
        download_name=photo["original_filename"],
        conditional=True,
    )


@daily_logbook.route("/student/daily-log/photo/<int:photo_id>/delete", methods=["POST"])
@role_required("student")
def delete_photo(photo_id):
    try:
        result = delete_logbook_photo(session["user_id"], photo_id)
        if result.get("ok"):
            flash("Photo evidence removed.", "success")
        else:
            flash(result.get("error") or "Unable to remove photo evidence.", "danger")
    except Exception as exc:
        print("daily logbook photo delete failed:", exc)
        result = {"ok": False}
        flash("Unable to remove photo evidence.", "danger")

    attendance_id = result.get("attendance_id")
    if attendance_id:
        return redirect(url_for("student.view_session", attendance_id=int(attendance_id)))
    return redirect(url_for("student.logbook"))
