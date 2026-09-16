from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.assigned_interns_service import get_supervisor_assigned_interns
from app.Services.internship_schedule_service import attendance_local_datetime
from app.Services.ojt_evaluation_bulk_service import save_supervisor_ojt_evaluations_bulk
from app.Services.ojt_evaluation_service import (
    get_supervisor_evaluation_context,
    reopen_supervisor_ojt_evaluation,
    save_supervisor_ojt_evaluation,
)


ojt_evaluation = Blueprint("ojt_evaluation", __name__)


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


def _classroom_evaluation_readiness(supervisor_id, class_id):
    """Return the classroom-level final-evaluation gate using local OJT dates.

    Weekly classrooms with a configured required-day count become available only
    when every enrolled intern has completed all required distinct OJT dates.
    Duplicate same-day attendance rows do not create extra OJT days, and stored
    timestamps are normalized with the same Nexora timezone rule as Logbook day
    numbering. Legacy classrooms without the weekly requirement remain editable.
    """
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """
            SELECT c.id,
                   COALESCE(cid.schedule_type, 'not_specified') AS schedule_type,
                   COALESCE(cid.required_days, 0) AS required_days
            FROM classrooms c
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.id = ? AND c.supervisor_id = ?
            LIMIT 1
            """,
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
            return {"exists": False, "configured": False, "available": False, "days_left": None}

        schedule_type = str(_row_value(classroom, "schedule_type", 1, "not_specified") or "not_specified").lower()
        required_days = int(_row_value(classroom, "required_days", 2, 0) or 0)
        configured = schedule_type == "weekly" and required_days > 0
        if not configured:
            return {
                "exists": True,
                "configured": False,
                "available": True,
                "required_days": required_days,
                "days_left": None,
                "minimum_completed_days": 0,
            }

        progress_rows = conn.execute(
            """
            SELECT cs.student_id, a.clock_in, a.status
            FROM classroom_students cs
            LEFT JOIN attendance a
              ON a.student_id = cs.student_id
             AND a.classroom_id = cs.classroom_id
            WHERE cs.classroom_id = ?
            ORDER BY cs.student_id ASC, a.clock_in ASC, a.id ASC
            """,
            (class_id,),
        ).fetchall()
        if not progress_rows:
            return {
                "exists": True,
                "configured": True,
                "available": False,
                "required_days": required_days,
                "days_left": required_days,
                "minimum_completed_days": 0,
            }

        completed_dates_by_student = {}
        for row in progress_rows:
            student_id = int(_row_value(row, "student_id", 0, 0) or 0)
            if not student_id:
                continue
            completed_dates = completed_dates_by_student.setdefault(student_id, set())
            if str(_row_value(row, "status", 2, "") or "") != "Completed":
                continue
            local_clock = attendance_local_datetime(_row_value(row, "clock_in", 1, None))
            if local_clock is not None:
                completed_dates.add(local_clock.date())

        completed_values = [
            len(completed_dates)
            for completed_dates in completed_dates_by_student.values()
        ]
        minimum_completed_days = min(completed_values) if completed_values else 0
        days_left = max(0, required_days - minimum_completed_days)
        return {
            "exists": True,
            "configured": True,
            "available": days_left == 0,
            "required_days": required_days,
            "days_left": days_left,
            "minimum_completed_days": minimum_completed_days,
        }
    finally:
        conn.close()


def _build_evaluation_directory(supervisor_id):
    assigned = get_supervisor_assigned_interns(supervisor_id)
    classrooms = []
    for group in assigned.get("interns", []):
        if group.get("is_legacy"):
            continue
        classroom = dict(group)
        classroom["interns"] = [dict(student) for student in group.get("interns", [])]
        classrooms.append(classroom)

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT classroom_id, student_id, status
            FROM ojt_evaluations
            WHERE supervisor_id = ?
            """,
            (supervisor_id,),
        ).fetchall()
    finally:
        conn.close()

    status_map = {}
    for row in rows:
        classroom_id = int(_row_value(row, "classroom_id", 0, 0) or 0)
        student_id = int(_row_value(row, "student_id", 1, 0) or 0)
        status = str(_row_value(row, "status", 2, "draft") or "draft").strip().lower()
        if classroom_id and student_id:
            status_map[(classroom_id, student_id)] = status

    total_interns = 0
    completed = 0
    for_review = 0
    not_started = 0
    ready_pending = 0

    for classroom in classrooms:
        classroom_id = int(classroom.get("class_id") or 0)
        readiness = _classroom_evaluation_readiness(supervisor_id, classroom_id)
        classroom["evaluation_schedule_configured"] = bool(readiness.get("configured"))
        classroom["evaluation_ready"] = bool(readiness.get("available"))
        classroom["required_days"] = int(readiness.get("required_days") or 0)
        classroom["days_left"] = readiness.get("days_left")
        classroom["minimum_completed_days"] = int(readiness.get("minimum_completed_days") or 0)

        submitted_count = 0
        draft_count = 0
        not_started_count = 0
        selectable_count = 0

        for student in classroom.get("interns", []):
            student_id = int(student.get("id") or 0)
            stored_status = status_map.get((classroom_id, student_id))
            if stored_status == "submitted":
                status_key = "submitted"
                status_label = "Submitted"
                submitted_count += 1
                completed += 1
            elif stored_status == "draft":
                status_key = "draft"
                status_label = "Draft"
                draft_count += 1
                for_review += 1
            else:
                status_key = "not_started"
                status_label = "Not Started"
                not_started_count += 1
                not_started += 1

            selectable = status_key != "submitted" and bool(readiness.get("available"))
            if selectable:
                selectable_count += 1
            student["evaluation_status_key"] = status_key
            student["evaluation_status"] = status_label
            student["evaluation_selectable"] = selectable
            total_interns += 1

        intern_count = len(classroom.get("interns", []))
        classroom["submitted_evaluations"] = submitted_count
        classroom["draft_evaluations"] = draft_count
        classroom["not_started_evaluations"] = not_started_count
        classroom["selectable_count"] = selectable_count
        classroom["evaluated_count"] = submitted_count
        classroom["evaluation_percentage"] = round((submitted_count / intern_count) * 100) if intern_count else 0
        classroom["pending_evaluations"] = max(0, intern_count - submitted_count)
        if classroom["evaluation_schedule_configured"] and classroom["evaluation_ready"]:
            ready_pending += classroom["pending_evaluations"]

    return {
        "classrooms": classrooms,
        "summary": {
            "total_interns": total_interns,
            "completed": completed,
            "for_review": for_review,
            "not_started": not_started,
            "ready_pending": ready_pending,
        },
    }


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


def _evaluation_redirect(class_id, student_id=None, return_to_directory=False):
    if return_to_directory:
        return redirect(url_for("ojt_evaluation.supervisor_evaluation_directory", class_id=class_id))
    if student_id:
        return redirect(
            url_for(
                "ojt_evaluation.supervisor_evaluations",
                class_id=class_id,
                student_id=student_id,
            )
        )
    return redirect(url_for("ojt_evaluation.supervisor_evaluations", class_id=class_id))


def _build_bulk_evaluation_context(supervisor_id, class_id, raw_student_ids):
    try:
        class_id = int(class_id)
        student_ids = []
        seen = set()
        for raw_student_id in raw_student_ids or []:
            student_id = int(raw_student_id)
            if student_id > 0 and student_id not in seen:
                student_ids.append(student_id)
                seen.add(student_id)
    except (TypeError, ValueError):
        return {"ok": False, "status_code": 400}

    if len(student_ids) < 2:
        return {"ok": False, "status_code": 400}

    directory = _build_evaluation_directory(supervisor_id)
    classroom_group = next(
        (
            classroom
            for classroom in directory.get("classrooms", [])
            if int(classroom.get("class_id") or 0) == class_id
        ),
        None,
    )
    if not classroom_group:
        return {"ok": False, "status_code": 404}

    students_by_id = {
        int(student.get("id") or 0): student
        for student in classroom_group.get("interns", [])
    }
    selected_students = []
    for student_id in student_ids:
        student = students_by_id.get(student_id)
        if not student:
            return {"ok": False, "status_code": 404}
        if not student.get("evaluation_selectable"):
            return {"ok": False, "status_code": 409}
        selected_students.append(student)

    return {
        "ok": True,
        "status_code": 200,
        "classroom": {
            "id": class_id,
            "name": classroom_group.get("classroom_name") or "Intern Classroom",
            "section": classroom_group.get("section") or "",
            "company_name": classroom_group.get("company_name") or "",
            "archived": bool(classroom_group.get("archived")),
        },
        "selected_students": selected_students,
    }


@ojt_evaluation.route("/supervisor/evaluations")
@role_required("supervisor")
def supervisor_evaluation_directory():
    context = _build_evaluation_directory(session["user_id"])
    return render_template(
        "supervisor/evaluations.html",
        classrooms=context["classrooms"],
        summary=context["summary"],
        target_class_id=request.args.get("class_id", type=int),
        active_page="evaluations",
    )


@ojt_evaluation.route(
    "/supervisor/classes/<int:class_id>/evaluations/bulk",
    methods=["GET", "POST"],
)
@role_required("supervisor")
def supervisor_bulk_evaluations(class_id):
    supervisor_id = session["user_id"]

    if request.method == "POST":
        readiness = _classroom_evaluation_readiness(supervisor_id, class_id)
        if readiness.get("configured") and not readiness.get("available"):
            flash(f"Official OJT Evaluation becomes available when this classroom reaches 0 days left. {readiness.get('days_left', 0)} day(s) remain.", "warning")
            return redirect(url_for("ojt_evaluation.supervisor_evaluation_directory", class_id=class_id))

        action = (request.form.get("action") or "").strip().lower()
        status = "submitted" if action == "submit" else "draft" if action == "save_draft" else None
        if not status:
            flash("Invalid bulk Official OJT Evaluation action.", "danger")
            return redirect(url_for("ojt_evaluation.supervisor_evaluation_directory", class_id=class_id))

        student_ids = request.form.getlist("student_id")
        result = save_supervisor_ojt_evaluations_bulk(
            supervisor_id=supervisor_id,
            classroom_id=class_id,
            student_ids=student_ids,
            status=status,
            items=_build_items_from_form(),
            overall_score=request.form.get("overall_score"),
            remarks=request.form.get("remarks"),
        )
        if result.get("ok"):
            count = int(result.get("saved_count") or 0)
            if status == "submitted":
                flash(f"Submitted {count} Official OJT Evaluations.", "success")
            else:
                flash(f"Saved drafts for {count} selected interns.", "success")
        else:
            flash(result.get("error") or "Unable to save the selected evaluations.", "danger")
        return redirect(url_for("ojt_evaluation.supervisor_evaluation_directory", class_id=class_id))

    context = _build_bulk_evaluation_context(
        supervisor_id,
        class_id,
        request.args.getlist("student_id"),
    )
    if not context.get("ok"):
        abort(int(context.get("status_code") or 400))

    if (request.args.get("modal") or "").strip() != "1":
        return redirect(url_for("ojt_evaluation.supervisor_evaluation_directory", class_id=class_id))

    return render_template(
        "components/supervisor_bulk_evaluation_modal_content.html",
        classroom=context["classroom"],
        selected_students=context["selected_students"],
        active_page="evaluations",
    )


@ojt_evaluation.route("/supervisor/classes/<int:class_id>/evaluations", methods=["GET", "POST"])
@role_required("supervisor")
def supervisor_evaluations(class_id):
    supervisor_id = session["user_id"]

    if request.method == "POST":
        return_to_directory = (request.form.get("return_to") or "").strip().lower() == "directory"
        student_id = request.form.get("student_id", type=int)
        if not student_id:
            flash("Choose an intern before saving an Official OJT Evaluation.", "danger")
            return _evaluation_redirect(class_id, return_to_directory=return_to_directory)

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
            return _evaluation_redirect(
                class_id,
                student_id=student_id,
                return_to_directory=return_to_directory,
            )

        readiness = _classroom_evaluation_readiness(supervisor_id, class_id)
        if readiness.get("configured") and not readiness.get("available"):
            flash(f"Official OJT Evaluation becomes available when this classroom reaches 0 days left. {readiness.get('days_left', 0)} day(s) remain.", "warning")
            return _evaluation_redirect(class_id, return_to_directory=True)

        status = "submitted" if action == "submit" else "draft" if action == "save_draft" else None
        if not status:
            flash("Invalid Official OJT Evaluation action.", "danger")
            return _evaluation_redirect(
                class_id,
                student_id=student_id,
                return_to_directory=return_to_directory,
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

        return _evaluation_redirect(
            class_id,
            student_id=student_id,
            return_to_directory=return_to_directory,
        )

    requested_student_id = request.args.get("student_id", type=int)
    context = get_supervisor_evaluation_context(
        supervisor_id=supervisor_id,
        classroom_id=class_id,
        student_id=requested_student_id,
    )
    if not context.get("ok"):
        abort(int(context.get("status_code") or 404))

    readiness = _classroom_evaluation_readiness(supervisor_id, class_id)
    template_context = {
        "classroom": context["classroom"],
        "students": context["students"],
        "selected_student": context["selected_student"],
        "evaluation": context["evaluation"],
        "evaluation_items": context["items"],
        "evaluation_readiness": readiness,
        "active_page": "evaluations",
    }

    if (request.args.get("modal") or "").strip() == "1":
        if not context["selected_student"]:
            abort(404)
        current_status = str((context.get("evaluation") or {}).get("status") or "").lower()
        if readiness.get("configured") and not readiness.get("available") and current_status != "submitted":
            abort(409)
        return render_template(
            "components/supervisor_evaluation_modal_content.html",
            **template_context,
        )

    return render_template(
        "classroom/supervisor_ojt_evaluation.html",
        **template_context,
    )
