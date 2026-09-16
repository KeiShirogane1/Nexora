from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.internship_schedule_service import attendance_local_datetime
from app.Services.logbook_photo_service import PHOTO_ROOT, get_logbook_photos, get_photo_for_supervisor
from app.Services.logbook_review_service import (
    get_student_review_page,
    get_supervisor_logbook_context,
    revise_daily_log,
    save_supervisor_review,
)
from app.Services.logbook_service import get_logbook_work_items
from app.Services.notification_service import create_notification
from app.Services.performance_rating_service import (
    get_daily_performance_rating_for_student,
    get_daily_performance_rating_for_supervisor,
    save_bulk_daily_performance_ratings,
    save_daily_performance_rating,
)


logbook_review = Blueprint("logbook_review", __name__)

MAX_ADDITIONAL_RATING_CRITERIA = 8
MAX_RATING_CRITERION_NAME_LENGTH = 100


def _row_value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except AttributeError:
        pass
    try:
        value = row[index]
        return default if value is None else value
    except (IndexError, KeyError, TypeError):
        return default


def _parse_rating_criteria(form):
    names = list(form.getlist("criterion_name"))
    values = list(form.getlist("criterion_rating"))
    if not names and not values:
        return [], None
    if len(names) != len(values):
        return [], "Each additional rating criterion needs both a name and rating."
    if len(names) > MAX_ADDITIONAL_RATING_CRITERIA:
        return [], f"Use up to {MAX_ADDITIONAL_RATING_CRITERIA} additional rating criteria."

    criteria = []
    for index, (raw_name, raw_value) in enumerate(zip(names, values), start=1):
        name = (raw_name or "").strip()
        value_text = (raw_value or "").strip()
        if not name and not value_text:
            continue
        if not name or not value_text:
            return [], "Complete or remove every additional rating criterion."
        if len(name) > MAX_RATING_CRITERION_NAME_LENGTH:
            return [], f"Criterion names must be {MAX_RATING_CRITERION_NAME_LENGTH} characters or fewer."
        try:
            rating_value = round(float(value_text), 1)
        except (TypeError, ValueError):
            return [], f"Choose a valid rating for {name}."
        if rating_value < 1.0 or rating_value > 5.0:
            return [], f"{name} must be rated from 1.0 to 5.0 stars."
        criteria.append(
            {
                "criterion_key": f"criterion_{index}",
                "criterion_name": name,
                "rating_value": rating_value,
                "max_value": 5.0,
                "sort_order": len(criteria),
            }
        )
    return criteria, None


def _replace_rating_criteria(attendance_id, criteria):
    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM daily_performance_rating_items WHERE attendance_id = ?",
            (attendance_id,),
        )
        for item in criteria:
            conn.execute(
                """
                INSERT INTO daily_performance_rating_items (
                    attendance_id,
                    criterion_key,
                    criterion_name,
                    rating_value,
                    max_value,
                    sort_order
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    attendance_id,
                    item["criterion_key"],
                    item["criterion_name"],
                    item["rating_value"],
                    item["max_value"],
                    item["sort_order"],
                ),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _attendance_day_details(conn, classroom_id, student_id, target_attendance_id):
    rows = conn.execute(
        """
        SELECT id, clock_in
        FROM attendance
        WHERE classroom_id = ? AND student_id = ?
        ORDER BY clock_in ASC, id ASC
        """,
        (classroom_id, student_id),
    ).fetchall()
    date_numbers = {}
    next_day = 1
    result = {"day_number": None, "date_label": "Unknown date"}
    for row in rows:
        attendance_id = int(_row_value(row, "id", 0, 0) or 0)
        local_clock = attendance_local_datetime(_row_value(row, "clock_in", 1, None))
        date_key = local_clock.date() if local_clock is not None else ("attendance", attendance_id)
        if date_key not in date_numbers:
            date_numbers[date_key] = next_day
            next_day += 1
        if attendance_id == int(target_attendance_id):
            result["day_number"] = date_numbers[date_key]
            if local_clock is not None:
                result["date_label"] = local_clock.strftime("%b %d, %Y")
            break
    return result


def _resync_work_score_after_log_removal(conn, assignment_id, student_id):
    row = conn.execute(
        """
        SELECT AVG(r.percentage) AS average_percentage,
               COUNT(r.attendance_id) AS rated_days
        FROM (
            SELECT l.attendance_id
            FROM logs l
            JOIN daily_log_work_links link ON link.log_id = l.id
            WHERE l.entry_type = 'daily'
              AND link.assignment_id = ?
              AND l.student_id = ?
            UNION
            SELECT l.attendance_id
            FROM logs l
            WHERE l.entry_type = 'daily'
              AND l.related_assignment_id = ?
              AND l.student_id = ?
        ) linked_days
        JOIN daily_performance_ratings r ON r.attendance_id = linked_days.attendance_id
        """,
        (assignment_id, student_id, assignment_id, student_id),
    ).fetchone()
    average_percentage = _row_value(row, "average_percentage", 0, None)
    rated_days = int(_row_value(row, "rated_days", 1, 0) or 0)

    if average_percentage is None or rated_days <= 0:
        conn.execute(
            "DELETE FROM classwork_scores WHERE assignment_id = ? AND student_id = ?",
            (assignment_id, student_id),
        )
        return

    percentage = round(float(average_percentage), 1)
    conn.execute(
        """
        INSERT INTO classwork_scores (
            assignment_id,
            student_id,
            score,
            max_score,
            percentage,
            grading_method,
            imported_at
        ) VALUES (?, ?, ?, 100, ?, 'daily_performance', CURRENT_TIMESTAMP)
        ON CONFLICT (assignment_id, student_id) DO UPDATE SET
            score = excluded.score,
            max_score = excluded.max_score,
            percentage = excluded.percentage,
            grading_method = excluded.grading_method,
            imported_at = excluded.imported_at
        """,
        (assignment_id, student_id, percentage, percentage),
    )


def _delete_daily_log_entry(
    log_id,
    actor_role,
    actor_id,
    classroom_id=None,
    student_id=None,
    remove_attendance=False,
):
    try:
        log_id = int(log_id)
        actor_id = int(actor_id)
        classroom_id = int(classroom_id) if classroom_id is not None else None
        student_id = int(student_id) if student_id is not None else None
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid Daily OJT entry."}

    conn = get_db_connection()
    photo_paths = []
    try:
        row = conn.execute(
            """
            SELECT l.id,
                   l.student_id,
                   l.attendance_id,
                   a.classroom_id,
                   a.clock_in,
                   c.name AS classroom_name,
                   c.supervisor_id
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            JOIN classrooms c ON c.id = a.classroom_id
            WHERE l.id = ? AND l.entry_type = 'daily'
            LIMIT 1
            """,
            (log_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "Daily OJT entry not found."}

        entry_student_id = int(_row_value(row, "student_id", 1, 0) or 0)
        attendance_id = int(_row_value(row, "attendance_id", 2, 0) or 0)
        entry_classroom_id = int(_row_value(row, "classroom_id", 3, 0) or 0)
        supervisor_id = int(_row_value(row, "supervisor_id", 6, 0) or 0)

        if actor_role == "supervisor":
            if supervisor_id != actor_id or classroom_id != entry_classroom_id:
                return {"ok": False, "error": "You can only remove Logbook entries from your own Intern Classroom."}
        elif actor_role == "admin":
            if student_id is not None and student_id != entry_student_id:
                return {"ok": False, "error": "This Logbook entry does not belong to the selected student."}
        else:
            return {"ok": False, "error": "You are not allowed to remove this Daily OJT entry."}

        if remove_attendance:
            shared_row = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE attendance_id = ? AND id <> ?",
                (attendance_id, log_id),
            ).fetchone()
            if int((shared_row[0] if shared_row else 0) or 0) > 0:
                return {
                    "ok": False,
                    "error": "This attendance session is still referenced by another Logbook entry, so its Time In/Out cannot be removed.",
                }

        day_details = _attendance_day_details(
            conn,
            entry_classroom_id,
            entry_student_id,
            attendance_id,
        )
        work_items = get_logbook_work_items(log_id, conn=conn)
        assignment_ids = [int(item["id"]) for item in work_items if item.get("id")]
        photo_rows = conn.execute(
            "SELECT relative_path FROM logbook_photos WHERE log_id = ?",
            (log_id,),
        ).fetchall()
        photo_paths = [str(_row_value(item, "relative_path", 0, "") or "") for item in photo_rows]

        conn.execute(
            "DELETE FROM daily_performance_rating_items WHERE attendance_id = ?",
            (attendance_id,),
        )
        conn.execute(
            "DELETE FROM daily_performance_ratings WHERE attendance_id = ?",
            (attendance_id,),
        )
        conn.execute("DELETE FROM logbook_reviews WHERE log_id = ?", (log_id,))
        conn.execute("DELETE FROM daily_log_work_links WHERE log_id = ?", (log_id,))
        conn.execute("DELETE FROM logbook_photos WHERE log_id = ?", (log_id,))
        conn.execute("DELETE FROM logs WHERE id = ? AND entry_type = 'daily'", (log_id,))

        for assignment_id in assignment_ids:
            _resync_work_score_after_log_removal(conn, assignment_id, entry_student_id)

        attendance_removed = False
        if remove_attendance:
            conn.execute(
                "DELETE FROM attendance WHERE id = ? AND student_id = ? AND classroom_id = ?",
                (attendance_id, entry_student_id, entry_classroom_id),
            )
            attendance_removed = True

        conn.commit()
        result = {
            "ok": True,
            "error": None,
            "log_id": log_id,
            "student_id": entry_student_id,
            "attendance_id": attendance_id,
            "classroom_id": entry_classroom_id,
            "classroom_name": _row_value(row, "classroom_name", 5, "Intern Classroom"),
            "day_number": day_details["day_number"],
            "date_label": day_details["date_label"],
            "work_count": len(assignment_ids),
            "attendance_removed": attendance_removed,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    root = PHOTO_ROOT.resolve()
    for relative_path in photo_paths:
        if not relative_path:
            continue
        try:
            path = (root / relative_path).resolve()
            if path != root and root in path.parents:
                path.unlink(missing_ok=True)
        except Exception:
            pass
    return result


def _admin_student_logbook_context(student_id):
    conn = get_db_connection()
    try:
        student = conn.execute(
            """
            SELECT u.id,
                   u.username,
                   u.email,
                   COALESCE(sp.first_name, '') AS first_name,
                   COALESCE(sp.last_name, '') AS last_name
            FROM users u
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE u.id = ? AND u.role = 'student'
            LIMIT 1
            """,
            (student_id,),
        ).fetchone()
        if not student:
            return None

        rows = conn.execute(
            """
            SELECT l.id,
                   l.attendance_id,
                   a.classroom_id,
                   a.clock_in,
                   a.clock_out,
                   a.hours_rendered,
                   a.status AS attendance_status,
                   c.name AS classroom_name,
                   c.section,
                   sup.username AS supervisor_name,
                   COALESCE(r.status, 'pending') AS review_status,
                   dpr.star_rating,
                   dpr.percentage,
                   dpr.comment AS rating_comment,
                   dpr.rated_at
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            JOIN classrooms c ON c.id = a.classroom_id
            LEFT JOIN users sup ON sup.id = c.supervisor_id
            LEFT JOIN logbook_reviews r ON r.log_id = l.id
            LEFT JOIN daily_performance_ratings dpr ON dpr.attendance_id = a.id
            WHERE l.student_id = ? AND l.entry_type = 'daily'
            ORDER BY a.clock_in DESC, l.id DESC
            """,
            (student_id,),
        ).fetchall()

        entries = []
        for row in rows:
            attendance_id = int(_row_value(row, "attendance_id", 1, 0) or 0)
            classroom_id = int(_row_value(row, "classroom_id", 2, 0) or 0)
            day = _attendance_day_details(conn, classroom_id, student_id, attendance_id)
            work_items = get_logbook_work_items(int(_row_value(row, "id", 0, 0)), conn=conn)
            criterion_rows = conn.execute(
                """
                SELECT criterion_name, rating_value, max_value
                FROM daily_performance_rating_items
                WHERE attendance_id = ?
                ORDER BY sort_order ASC, criterion_key ASC
                """,
                (attendance_id,),
            ).fetchall()
            criteria = [
                {
                    "criterion_name": _row_value(item, "criterion_name", 0, "") or "",
                    "rating_value": float(_row_value(item, "rating_value", 1, 0) or 0),
                    "max_value": float(_row_value(item, "max_value", 2, 5) or 5),
                }
                for item in criterion_rows
            ]
            entries.append(
                {
                    "id": int(_row_value(row, "id", 0, 0)),
                    "attendance_id": attendance_id,
                    "classroom_id": classroom_id,
                    "classroom_name": _row_value(row, "classroom_name", 7, "Intern Classroom"),
                    "section": _row_value(row, "section", 8, "") or "",
                    "supervisor_name": _row_value(row, "supervisor_name", 9, "") or "",
                    "day_number": day["day_number"],
                    "date": day["date_label"],
                    "hours_rendered": _row_value(row, "hours_rendered", 5, None),
                    "attendance_status": _row_value(row, "attendance_status", 6, "Open"),
                    "review_status": _row_value(row, "review_status", 10, "pending"),
                    "star_rating": _row_value(row, "star_rating", 11, None),
                    "percentage": _row_value(row, "percentage", 12, None),
                    "rating_comment": _row_value(row, "rating_comment", 13, "") or "",
                    "rated_at": _row_value(row, "rated_at", 14, None),
                    "criteria": criteria,
                    "work_titles": [item["title"] for item in work_items],
                }
            )

        first_name = (_row_value(student, "first_name", 3, "") or "").strip()
        last_name = (_row_value(student, "last_name", 4, "") or "").strip()
        username = (_row_value(student, "username", 1, "") or "").strip()
        return {
            "student": {
                "id": int(_row_value(student, "id", 0, student_id)),
                "username": username,
                "email": _row_value(student, "email", 2, "") or "",
                "display_name": " ".join(part for part in (first_name, last_name) if part).strip() or username,
            },
            "entries": entries,
        }
    finally:
        conn.close()


def _notify_removed_logbook(result, actor_label):
    day_label = f"Day {result['day_number']}" if result.get("day_number") else "a Daily OJT day"
    if result.get("attendance_removed"):
        detail = "The related attendance session, Time In/Out, and rendered hours were removed too."
    else:
        detail = "Your attendance Time In/Out and rendered hours were not deleted."
    message = (
        f"Your {day_label} Logbook ({result['date_label']}) in {result['classroom_name']} was removed by {actor_label}. "
        f"{detail}"
    )
    create_notification(
        int(result["student_id"]),
        "Daily OJT Logbook Removed",
        message,
        "feedback",
        link_url=url_for("student.logbook", classroom_id=int(result["classroom_id"])),
    )


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

    selected_entry = context["selected_entry"]
    daily_rating = None
    if selected_entry:
        daily_rating = get_daily_performance_rating_for_supervisor(
            supervisor_id=session["user_id"],
            classroom_id=class_id,
            attendance_id=selected_entry["attendance_id"],
        )

    return render_template(
        "classroom/supervisor_logbook_review.html",
        classroom=context["classroom"],
        entries=context["entries"],
        selected_entry=selected_entry,
        selected_photos=context["selected_photos"],
        summary=context["summary"],
        daily_rating=daily_rating,
        active_page="classes",
    )


@logbook_review.route(
    "/supervisor/classes/<int:class_id>/logbook/<int:log_id>/review",
    methods=["POST"],
)
@role_required("supervisor")
def review_daily_log(class_id, log_id):
    status = (request.form.get("status") or "").strip().lower()
    rating_result = None

    if status in {"reviewed", "approved"}:
        context = get_supervisor_logbook_context(
            supervisor_id=session["user_id"],
            classroom_id=class_id,
            selected_log_id=log_id,
        )
        if not context.get("ok"):
            abort(int(context.get("status_code") or 404))
        entry = context.get("selected_entry")
        if not entry:
            abort(404)

        star_rating = (request.form.get("star_rating") or "").strip()
        existing_rating = get_daily_performance_rating_for_supervisor(
            supervisor_id=session["user_id"],
            classroom_id=class_id,
            attendance_id=entry["attendance_id"],
        )
        if status == "approved" and not star_rating and not existing_rating:
            flash("Choose an Overall Daily Rating before approving this Daily OJT entry.", "danger")
            return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id, log_id=log_id))

        if star_rating:
            criteria, criteria_error = _parse_rating_criteria(request.form)
            if criteria_error:
                flash(criteria_error, "danger")
                return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id, log_id=log_id))
            try:
                rating_result = save_daily_performance_rating(
                    supervisor_id=session["user_id"],
                    classroom_id=class_id,
                    attendance_id=entry["attendance_id"],
                    star_rating=star_rating,
                    comment=request.form.get("rating_comment"),
                )
                if rating_result.get("ok"):
                    _replace_rating_criteria(entry["attendance_id"], criteria)
            except Exception as exc:
                print("daily performance rating during review failed:", exc)
                rating_result = {"ok": False, "error": "Unable to save the Daily Performance rating."}
            if not rating_result.get("ok"):
                flash(rating_result.get("error") or "Unable to save the Daily Performance rating.", "danger")
                return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id, log_id=log_id))

    try:
        result = save_supervisor_review(
            supervisor_id=session["user_id"],
            classroom_id=class_id,
            log_id=log_id,
            status=status,
            comments=request.form.get("comments"),
        )
    except Exception as exc:
        print("daily logbook review failed:", exc)
        result = {"ok": False, "error": "Unable to save the Daily OJT review."}

    if result.get("ok"):
        if rating_result and rating_result.get("ok"):
            linked_count = len(rating_result.get("linked_assignment_ids") or [])
            flash(
                f"Daily OJT entry marked {result['status_label']} and rated {rating_result['star_rating']:.1f} stars "
                f"({rating_result['percentage']:.1f}%). Applied to {linked_count} linked Work item"
                f"{'s' if linked_count != 1 else ''}.",
                "success",
            )
        else:
            flash(f"Daily OJT entry marked {result['status_label']}.", "success")

        if result.get("status") in {"reviewed", "approved"} and not rating_result:
            try:
                daily_rating = get_daily_performance_rating_for_supervisor(
                    supervisor_id=session["user_id"],
                    classroom_id=class_id,
                    attendance_id=result["attendance_id"],
                )
            except Exception as exc:
                print("daily performance rating lookup failed:", exc)
                daily_rating = None
            if not daily_rating:
                flash(
                    "Review saved, but this Daily OJT entry is not graded yet. Choose Daily Performance and save the Overall Daily Rating to update linked Work scores, ML Insights, and Reports.",
                    "warning",
                )
        try:
            rating_note = ""
            if rating_result and rating_result.get("ok"):
                rating_note = f" Your Daily Performance is {rating_result['star_rating']:.1f} stars ({rating_result['percentage']:.1f}%)."
            create_notification(
                int(result["student_id"]),
                "Daily OJT Logbook Review",
                f"Your Daily OJT entry was marked {result['status_label']}.{rating_note}",
                "feedback",
                link_url=url_for("logbook_review.student_review", log_id=log_id),
            )
        except Exception as exc:
            print("daily logbook review notification failed:", exc)
    else:
        flash(result.get("error") or "Unable to save the Daily OJT review.", "danger")

    return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id, log_id=log_id))


@logbook_review.route(
    "/supervisor/classes/<int:class_id>/logbook/<int:log_id>/rating",
    methods=["POST"],
)
@role_required("supervisor")
def rate_daily_performance(class_id, log_id):
    context = get_supervisor_logbook_context(
        supervisor_id=session["user_id"],
        classroom_id=class_id,
        selected_log_id=log_id,
    )
    if not context.get("ok"):
        abort(int(context.get("status_code") or 404))

    entry = context.get("selected_entry")
    if not entry:
        abort(404)

    criteria, criteria_error = _parse_rating_criteria(request.form)
    if criteria_error:
        flash(criteria_error, "danger")
        return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id, log_id=log_id))

    try:
        result = save_daily_performance_rating(
            supervisor_id=session["user_id"],
            classroom_id=class_id,
            attendance_id=entry["attendance_id"],
            star_rating=request.form.get("star_rating"),
            comment=request.form.get("rating_comment"),
        )
        if result.get("ok"):
            _replace_rating_criteria(entry["attendance_id"], criteria)
    except Exception as exc:
        print("daily performance rating failed:", exc)
        result = {"ok": False, "error": "Unable to save the daily performance rating."}

    if result.get("ok"):
        linked_assignment_ids = result.get("linked_assignment_ids") or []
        linked_note = ""
        if linked_assignment_ids:
            linked_note = (
                f" Applied to {len(linked_assignment_ids)} linked Work "
                f"item{'s' if len(linked_assignment_ids) != 1 else ''}."
            )
        criteria_note = f" {len(criteria)} additional criterion{'a' if len(criteria) == 1 else ' criteria'} saved." if criteria else ""
        flash(
            f"Daily performance saved: {result['star_rating']:.1f} stars · {result['percentage']:.1f}%.{linked_note}{criteria_note}",
            "success",
        )
        try:
            create_notification(
                int(result["student_id"]),
                "Daily Performance Rating",
                f"Your daily performance was rated {result['star_rating']:.1f} stars ({result['percentage']:.1f}%).",
                "feedback",
                link_url=url_for("logbook_review.student_review", log_id=log_id),
            )
        except Exception as exc:
            print("daily performance rating notification failed:", exc)
    else:
        flash(result.get("error") or "Unable to save the daily performance rating.", "danger")

    return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id, log_id=log_id))


@logbook_review.route(
    "/supervisor/classes/<int:class_id>/logbook/ratings/bulk",
    methods=["POST"],
)
@role_required("supervisor")
def bulk_rate_daily_performance(class_id):
    criteria, criteria_error = _parse_rating_criteria(request.form)
    if criteria_error:
        flash(criteria_error, "danger")
        return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id))

    try:
        result = save_bulk_daily_performance_ratings(
            supervisor_id=session["user_id"],
            classroom_id=class_id,
            log_ids=request.form.getlist("log_ids"),
            star_rating=request.form.get("star_rating"),
            comment=request.form.get("rating_comment"),
        )
        if result.get("ok"):
            for recipient in result.get("recipients", []):
                _replace_rating_criteria(int(recipient["attendance_id"]), criteria)
    except Exception as exc:
        print("bulk daily performance rating failed:", exc)
        result = {"ok": False, "error": "Unable to save the bulk daily performance rating."}

    if result.get("ok"):
        flash(
            f"Daily performance saved for {result['count']} entr{'y' if result['count'] == 1 else 'ies'}: "
            f"{result['star_rating']:.1f} stars · {result['percentage']:.1f}%.",
            "success",
        )
        for recipient in result.get("recipients", []):
            try:
                create_notification(
                    int(recipient["student_id"]),
                    "Daily Performance Rating",
                    f"Your daily performance was rated {result['star_rating']:.1f} stars ({result['percentage']:.1f}%).",
                    "feedback",
                    link_url=url_for(
                        "logbook_review.student_review",
                        log_id=int(recipient["log_id"]),
                    ),
                )
            except Exception as exc:
                print("bulk daily performance notification failed:", exc)
    else:
        flash(result.get("error") or "Unable to save the bulk daily performance rating.", "danger")

    selected_log_id = None
    recipients = result.get("recipients") or []
    if recipients:
        selected_log_id = int(recipients[0]["log_id"])
    if selected_log_id:
        return redirect(
            url_for(
                "logbook_review.supervisor_logbook",
                class_id=class_id,
                log_id=selected_log_id,
            )
        )
    return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id))


@logbook_review.route(
    "/supervisor/classes/<int:class_id>/logbook/<int:log_id>/delete",
    methods=["POST"],
)
@role_required("supervisor")
def supervisor_delete_daily_log(class_id, log_id):
    remove_attendance = (request.form.get("remove_attendance") or "").strip() == "1"
    try:
        result = _delete_daily_log_entry(
            log_id=log_id,
            actor_role="supervisor",
            actor_id=session["user_id"],
            classroom_id=class_id,
            remove_attendance=remove_attendance,
        )
    except Exception as exc:
        print("supervisor daily logbook removal failed:", exc)
        result = {"ok": False, "error": "Unable to remove the Daily OJT Logbook entry."}

    if result.get("ok"):
        day_label = f"Day {result['day_number']}" if result.get("day_number") else "Daily OJT"
        if result.get("attendance_removed"):
            detail = "The related attendance session and rendered hours were removed too."
        else:
            detail = "Attendance and rendered hours were preserved."
        flash(f"{day_label} Logbook ({result['date_label']}) was removed. {detail}", "success")
        try:
            _notify_removed_logbook(result, "your supervisor")
        except Exception as exc:
            print("daily logbook removal notification failed:", exc)
    else:
        flash(result.get("error") or "Unable to remove the Daily OJT Logbook entry.", "danger")

    return redirect(url_for("logbook_review.supervisor_logbook", class_id=class_id))


@logbook_review.route("/admin/student/<int:student_id>/logbook")
@role_required("admin")
def admin_student_logbooks(student_id):
    context = _admin_student_logbook_context(student_id)
    if not context:
        abort(404)
    return render_template(
        "admin/student_logbooks.html",
        student=context["student"],
        entries=context["entries"],
        active_page="users",
    )


@logbook_review.route(
    "/admin/student/<int:student_id>/logbook/<int:log_id>/delete",
    methods=["POST"],
)
@role_required("admin")
def admin_delete_daily_log(student_id, log_id):
    remove_attendance = (request.form.get("remove_attendance") or "").strip() == "1"
    try:
        result = _delete_daily_log_entry(
            log_id=log_id,
            actor_role="admin",
            actor_id=session["user_id"],
            student_id=student_id,
            remove_attendance=remove_attendance,
        )
    except Exception as exc:
        print("admin daily logbook removal failed:", exc)
        result = {"ok": False, "error": "Unable to remove the Daily OJT Logbook entry."}

    if result.get("ok"):
        day_label = f"Day {result['day_number']}" if result.get("day_number") else "Daily OJT"
        if result.get("attendance_removed"):
            detail = "The related attendance session and rendered hours were removed too."
        else:
            detail = "Attendance and rendered hours were preserved."
        flash(f"{day_label} Logbook ({result['date_label']}) was removed. {detail}", "success")
        try:
            _notify_removed_logbook(result, "an administrator")
        except Exception as exc:
            print("admin daily logbook removal notification failed:", exc)
    else:
        flash(result.get("error") or "Unable to remove the Daily OJT Logbook entry.", "danger")

    return redirect(url_for("logbook_review.admin_student_logbooks", student_id=student_id))


@logbook_review.route("/supervisor/classes/<int:class_id>/logbook/photo/<int:photo_id>")
@role_required("supervisor")
def supervisor_photo(class_id, photo_id):
    photo = get_photo_for_supervisor(session["user_id"], class_id, photo_id)
    if not photo:
        abort(404)
    return send_file(
        photo["path"],
        mimetype=photo["mime_type"],
        as_attachment=False,
        download_name=photo["original_filename"],
        conditional=True,
    )


@logbook_review.route("/supervisor/classes/<int:class_id>/logbook/photo/<int:photo_id>/download")
@role_required("supervisor")
def supervisor_photo_download(class_id, photo_id):
    photo = get_photo_for_supervisor(session["user_id"], class_id, photo_id)
    if not photo:
        abort(404)
    return send_file(
        photo["path"],
        mimetype=photo["mime_type"],
        as_attachment=True,
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
        daily_rating=get_daily_performance_rating_for_student(
            session["user_id"],
            entry["attendance_id"],
        ),
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
