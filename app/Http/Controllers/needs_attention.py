"""Supervisor Needs Attention review queue for existing OJT evidence."""

from flask import Blueprint, abort, render_template, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.classwork_ml_service import classify_numeric_performance
from app.Services.intern_profile_service import get_supervisor_intern_profile
from app.Services.ojt_evaluation_service import get_supervisor_evaluation_context


needs_attention = Blueprint("needs_attention", __name__)


def _value(row, key, index=0, default=None):
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


def _signal(category, dimension, title, detail):
    return {
        "category": category,
        "dimension": dimension,
        "title": title,
        "detail": detail,
    }


def _build_attention_signals(profile, official_evaluation):
    """Return factual review signals without creating a combined risk score."""
    signals = []
    attendance = profile.get("attendance_summary") or {}
    daily = (profile.get("daily_performance") or {}).get("summary") or {}
    logbook = profile.get("logbook_summary") or {}
    work = profile.get("work_summary") or {}

    completed_days = int(attendance.get("completed_days", 0) or 0)
    rated_days = int(daily.get("rated_days", 0) or 0)
    if completed_days > rated_days:
        missing_ratings = completed_days - rated_days
        signals.append(
            _signal(
                "evidence_gap",
                "Daily Performance",
                "Completed OJT days still need ratings",
                f"{missing_ratings} completed day{'s' if missing_ratings != 1 else ''} do not yet have a manual Daily Performance rating.",
            )
        )

    logbook_total = int(logbook.get("total", 0) or 0)
    if completed_days > 0 and logbook_total == 0:
        signals.append(
            _signal(
                "evidence_gap",
                "Daily Logbook",
                "No logbook evidence yet",
                "The intern has completed OJT attendance days but has no classroom-scoped Daily Logbook entry yet.",
            )
        )

    revision_requested = int(logbook.get("revision_requested", 0) or 0)
    if revision_requested > 0:
        signals.append(
            _signal(
                "workflow",
                "Daily Logbook",
                "Logbook revision requested",
                f"{revision_requested} Daily Logbook entr{'y' if revision_requested == 1 else 'ies'} currently require revision.",
            )
        )

    assigned_count = int(work.get("assigned_count", 0) or 0)
    graded_count = int(work.get("graded_count", 0) or 0)
    work_average = work.get("average_percentage")
    if assigned_count > 0 and graded_count == 0:
        signals.append(
            _signal(
                "evidence_gap",
                "Work",
                "No reviewed Work score yet",
                "Work is assigned, but there is no reviewed numeric Work result yet for this intern.",
            )
        )
    elif work_average is not None:
        work_label = classify_numeric_performance(float(work_average))
        if work_label in ("Fair", "Needs Improvement"):
            signals.append(
                _signal(
                    "performance",
                    "Work",
                    f"Work performance is {work_label}",
                    f"The current reviewed Work average is {float(work_average):.1f}%. This signal is based only on Work/gradebook evidence.",
                )
            )

    if official_evaluation and official_evaluation.get("status") == "draft":
        signals.append(
            _signal(
                "workflow",
                "Official Evaluation",
                "Official Evaluation is still draft",
                "A manual Official OJT Evaluation has been started but has not been submitted.",
            )
        )

    return signals


@needs_attention.route("/supervisor/classes/<int:class_id>/needs-attention")
@role_required("supervisor")
def supervisor_needs_attention(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom_row = conn.execute(
            """SELECT id, supervisor_id, name, section, description, code, archived
               FROM classrooms WHERE id = ? AND supervisor_id = ?""",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom_row:
            abort(404)

        students = conn.execute(
            """SELECT u.id, u.username, u.email,
                      COALESCE(p.student_id, '') AS student_number
               FROM classroom_students cs
               JOIN users u ON u.id = cs.student_id
               LEFT JOIN student_profiles p ON p.user_id = u.id
               WHERE cs.classroom_id = ?
               ORDER BY LOWER(u.username), LOWER(u.email), u.id""",
            (class_id,),
        ).fetchall()

        classroom = {
            "id": int(_value(classroom_row, "id", 0, 0)),
            "name": _value(classroom_row, "name", 2, ""),
            "section": _value(classroom_row, "section", 3, ""),
            "description": _value(classroom_row, "description", 4, ""),
            "code": _value(classroom_row, "code", 5, ""),
            "archived": bool(_value(classroom_row, "archived", 6, 0)),
        }
    finally:
        conn.close()

    review_items = []
    category_counts = {"performance": 0, "evidence_gap": 0, "workflow": 0}

    for row in students:
        student_id = int(_value(row, "id", 0, 0) or 0)
        profile = get_supervisor_intern_profile(
            supervisor_id=supervisor_id,
            classroom_id=class_id,
            student_id=student_id,
        )
        if not profile.get("ok"):
            continue

        evaluation_context = get_supervisor_evaluation_context(
            supervisor_id=supervisor_id,
            classroom_id=class_id,
            student_id=student_id,
        )
        official_evaluation = evaluation_context.get("evaluation") if evaluation_context.get("ok") else None
        signals = _build_attention_signals(profile, official_evaluation)
        if not signals:
            continue

        for signal in signals:
            category_counts[signal["category"]] += 1

        student = profile.get("student") or {}
        review_items.append(
            {
                "id": student_id,
                "name": student.get("display_name") or _value(row, "username", 1, "Student"),
                "student_number": student.get("student_number") or _value(row, "student_number", 3, ""),
                "email": student.get("email") or _value(row, "email", 2, ""),
                "signals": signals,
            }
        )

    return render_template(
        "classroom/supervisor_needs_attention.html",
        classroom=classroom,
        review_items=review_items,
        total_interns=len(students),
        category_counts=category_counts,
        active_page="classes",
    )
