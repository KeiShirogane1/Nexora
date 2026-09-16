from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.internship_schedule_service import (
    app_local_now,
    attendance_local_datetime,
    get_student_schedule_state,
)
from app.Services.logbook_service import save_daily_log
from app.Services.logbook_photo_service import (
    add_logbook_photos,
    add_photos_for_attendance,
    delete_logbook_photo,
    get_photo_for_student,
)


daily_logbook = Blueprint("daily_logbook", __name__)


@daily_logbook.before_app_request
def _enforce_student_clock_in_schedule():
    """Reject duplicate or out-of-schedule OJT Clock In posts before attendance is created."""
    if request.endpoint != "student.clock_in" or request.method != "POST":
        return None
    if session.get("role") != "student" or not session.get("user_id"):
        return None

    try:
        state = get_student_schedule_state(session["user_id"])
    except Exception as exc:
        # Keep the existing student Clock In route authoritative if schedule
        # state cannot be loaded for an unrelated legacy-data reason.
        print("clock-in schedule check skipped:", exc)
        return None

    classroom_id = state.get("classroom_id")
    if not classroom_id or state.get("can_clock_in", True):
        return None

    flash(
        state.get("clock_in_block_reason")
        or "Clock In is not available for this OJT day.",
        "warning",
    )
    return redirect(url_for("student.logbook", classroom_id=int(classroom_id)))


@daily_logbook.route("/student/daily-log/save", methods=["POST"])
@role_required("student")
def save_daily_entry():
    attendance_id = request.form.get("attendance_id")
    related_assignment_ids = request.form.getlist("related_assignment_ids")
    result = save_daily_log(
        student_id=session["user_id"],
        attendance_id=attendance_id,
        accomplishment=request.form.get("accomplishment"),
        reflection=request.form.get("reflection"),
        challenges=request.form.get("challenges"),
        related_assignment_ids=related_assignment_ids,
        # Keep compatibility with the pre-Phase-2 single-select form if an old
        # browser tab submits before its page is refreshed after deployment.
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


@daily_logbook.route(
    "/student/daily-log/attendance/<int:attendance_id>/edit",
    methods=["GET", "POST"],
)
@role_required("student")
def edit_today_daily_entry(attendance_id):
    """Allow a student to edit an existing Daily OJT entry only on its local OJT date."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT l.id,
                   l.content,
                   COALESCE(l.reflection, '') AS reflection,
                   COALESCE(l.challenges, '') AS challenges,
                   a.clock_in,
                   a.classroom_id
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            WHERE l.attendance_id = ?
              AND l.student_id = ?
              AND COALESCE(l.entry_type, 'daily') = 'daily'
            ORDER BY l.id DESC
            LIMIT 1
            """,
            (attendance_id, session["user_id"]),
        ).fetchone()
        if not row:
            abort(404)

        local_clock = attendance_local_datetime(row[4])
        classroom_id = row[5]
        if local_clock is None or local_clock.date() != app_local_now().date():
            flash("Previous OJT days are read-only. You can edit only today's Daily OJT Logbook entry.", "warning")
            if classroom_id is not None:
                return redirect(url_for("student.logbook", classroom_id=int(classroom_id)))
            return redirect(url_for("student.logbook"))

        if request.method == "POST":
            accomplishment = (request.form.get("content") or "").strip()
            reflection = (request.form.get("reflection") or "").strip()
            challenges = (request.form.get("challenges") or "").strip()
            if not accomplishment:
                flash("Daily accomplishment is required.", "danger")
            else:
                conn.execute(
                    """
                    UPDATE logs
                    SET content = ?, reflection = ?, challenges = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND student_id = ?
                    """,
                    (accomplishment, reflection, challenges, row[0], session["user_id"]),
                )
                conn.commit()
                flash("Today's Daily OJT Logbook entry was updated.", "success")
                if classroom_id is not None:
                    return redirect(url_for("student.logbook", classroom_id=int(classroom_id)))
                return redirect(url_for("student.logbook"))

        return render_template(
            "student/edit_log.html",
            log=row,
            log_content=row[1] or "",
            log_reflection=row[2] or "",
            log_challenges=row[3] or "",
            active_page="logbook",
        )
    finally:
        conn.close()


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


@daily_logbook.route("/student/daily-log/photo/<int:photo_id>/download")
@role_required("student")
def download_photo(photo_id):
    photo = get_photo_for_student(session["user_id"], photo_id)
    if not photo:
        abort(404)
    return send_file(
        photo["path"],
        mimetype=photo["mime_type"],
        as_attachment=True,
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
