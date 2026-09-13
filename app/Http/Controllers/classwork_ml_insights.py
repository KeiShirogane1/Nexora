"""ML Performance Insights UI — supervisor and student views."""

from flask import Blueprint, abort, render_template, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.classwork_ml_service import (
    build_student_ml_analysis,
    build_student_performance_features,
    classify_numeric_performance,
)
from app.Services.intern_profile_service import get_supervisor_intern_profile
from app.Services.ml_recommendation_service import build_recommendation_from_features
from app.Services.ojt_evaluation_service import get_supervisor_evaluation_context

classwork_ml_insights = Blueprint("classwork_ml_insights", __name__)


def _value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            return row[key]
    except AttributeError:
        pass
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return default


def _get_latest_feedback_text(student_id, class_id):
    """Return feedback that belongs to this classroom's evidence context."""
    conn = get_db_connection()
    try:
        # Current Work feedback is scoped exactly through its assignment.
        try:
            sub = conn.execute(
                """SELECT s.feedback
                   FROM classwork_submissions s
                   JOIN classroom_assignments a ON a.id = s.assignment_id
                   WHERE s.student_id = ? AND a.classroom_id = ?
                     AND s.feedback IS NOT NULL AND TRIM(s.feedback) != ''
                   ORDER BY s.submitted_at DESC, s.id DESC LIMIT 1""",
                (student_id, class_id),
            ).fetchone()
            if sub:
                comment = _value(sub, "feedback", 0)
                if comment and str(comment).strip():
                    return str(comment).strip()
        except Exception:
            pass

        # Legacy feedback has no classroom_id. Constrain it to the classroom
        # owner so feedback from another supervisor is never pulled in.
        try:
            fb = conn.execute(
                """SELECT f.comment
                   FROM feedback f
                   WHERE f.student_id = ?
                     AND f.supervisor_id = (
                         SELECT supervisor_id FROM classrooms WHERE id = ?
                     )
                     AND f.comment IS NOT NULL AND TRIM(f.comment) != ''
                   ORDER BY f.created_at DESC, f.id DESC LIMIT 1""",
                (student_id, class_id),
            ).fetchone()
            if fb:
                comment = _value(fb, "comment", 0)
                if comment and str(comment).strip():
                    return str(comment).strip()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return ""


def _empty_feedback_analysis():
    return {
        "performance_label": None,
        "nb_prediction": None,
        "svm_prediction": None,
        "sentiment": None,
        "competency": None,
        "recommendation": None,
        "confidence": 0.0,
        "is_empty": True,
    }


def _normalize_analysis_evidence(analysis):
    """Keep missing evidence distinct from an actual performance result."""
    features = analysis.get("features") or {}
    feedback_analysis = analysis.get("feedback_analysis") or _empty_feedback_analysis()
    has_performance_data = (
        features.get("average_percentage") is not None
        and int(features.get("graded_count", 0) or 0) > 0
    )
    has_feedback = not bool(feedback_analysis.get("is_empty", True))

    analysis["features"] = features
    analysis["feedback_analysis"] = feedback_analysis
    analysis["has_performance_data"] = has_performance_data
    if not has_performance_data:
        analysis["numeric_performance_label"] = "No Data"
        analysis["performance_label"] = "No Data"
    if not has_feedback:
        analysis["sentiment"] = None
        analysis["competency"] = None
        analysis["recommendation"] = None
        analysis["confidence"] = 0.0
    return analysis


def _safe_ml_analysis(student_id, class_id, feedback_text):
    try:
        analysis = build_student_ml_analysis(
            student_id,
            class_id,
            feedback_text=feedback_text,
        )
    except Exception:
        # Preserve numeric evidence if the predictor fails, but do not invent
        # feedback classifications, sentiment, competency, or recommendations.
        features = build_student_performance_features(student_id, class_id)
        numeric_label = classify_numeric_performance(features.get("average_percentage"))
        analysis = {
            "student_id": student_id,
            "class_id": class_id,
            "features": features,
            "numeric_performance_label": numeric_label,
            "feedback_analysis": _empty_feedback_analysis(),
            "performance_label": numeric_label,
            "sentiment": None,
            "competency": None,
            "recommendation": None,
            "confidence": 0.0,
        }
    return _normalize_analysis_evidence(analysis)


def _build_work_recommendation(analysis):
    features = analysis.get("features") or {}
    feedback_analysis = analysis.get("feedback_analysis") or _empty_feedback_analysis()
    if not analysis.get("has_performance_data", False):
        total = int(features.get("total_count", 0) or 0)
        basis = ["performance label: No Data"]
        basis.append("no assignments in this class" if total == 0 else "no grades yet")
        if feedback_analysis.get("is_empty", True):
            basis.append("no feedback text available")
        return {
            "performance_label": "No Data",
            "overall_percentage": None,
            "completion_rate": float(features.get("completion_rate", 0.0) or 0.0),
            "graded_count": int(features.get("graded_count", 0) or 0),
            "total_count": total,
            "recommendation": "",
            "priority": "none",
            "basis": basis,
            "has_feedback": not bool(feedback_analysis.get("is_empty", True)),
            "feedback_label": feedback_analysis.get("performance_label"),
            "sentiment": feedback_analysis.get("sentiment"),
        }

    try:
        return build_recommendation_from_features(
            features,
            feedback_analysis,
            performance_label=analysis.get("numeric_performance_label"),
        )
    except Exception:
        return {
            "performance_label": analysis.get("numeric_performance_label"),
            "overall_percentage": features.get("average_percentage"),
            "completion_rate": features.get("completion_rate", 0.0),
            "recommendation": analysis.get("recommendation") or "",
            "priority": "medium",
            "basis": [],
        }


def _build_cohort_summary(class_id, supervisor_id, students):
    """Aggregate classroom evidence without combining dimensions into a grade."""
    total_interns = len(students)
    work_scores = []
    work_completion_rates = []
    work_total_count = 0
    work_reviewed_count = 0
    work_interns = 0
    work_distribution = {
        "Excellent": 0,
        "Very Satisfactory": 0,
        "Satisfactory": 0,
        "Fair": 0,
        "Needs Improvement": 0,
        "No Data": 0,
    }

    for student in students:
        student_id = int(_value(student, "id", 0, 0) or 0)
        features = build_student_performance_features(student_id, class_id)
        average = features.get("average_percentage")
        total_count = int(features.get("total_count", 0) or 0)
        graded_count = int(features.get("graded_count", 0) or 0)
        completion_rate = float(features.get("completion_rate", 0.0) or 0.0)

        work_total_count += total_count
        work_reviewed_count += graded_count
        work_completion_rates.append(completion_rate)
        if total_count > 0:
            work_interns += 1

        if average is None:
            work_distribution["No Data"] += 1
        else:
            average_value = float(average)
            work_scores.append(average_value)
            label = classify_numeric_performance(average_value)
            if label not in work_distribution:
                label = "No Data"
            work_distribution[label] += 1

    conn = get_db_connection()
    try:
        attendance_row = conn.execute(
            """
            SELECT COUNT(DISTINCT student_id) AS intern_count,
                   COALESCE(SUM(CASE WHEN COALESCE(status, '') <> 'Open' THEN COALESCE(hours_rendered, 0) ELSE 0 END), 0) AS total_hours
            FROM attendance
            WHERE classroom_id = ?
            """,
            (class_id,),
        ).fetchone()
        daily_row = conn.execute(
            """
            SELECT COUNT(DISTINCT a.student_id) AS intern_count,
                   COUNT(r.attendance_id) AS rating_count,
                   AVG(r.percentage) AS average_percentage
            FROM daily_performance_ratings r
            JOIN attendance a ON a.id = r.attendance_id
            WHERE a.classroom_id = ?
            """,
            (class_id,),
        ).fetchone()
        logbook_row = conn.execute(
            """
            SELECT COUNT(DISTINCT l.student_id) AS intern_count,
                   COUNT(l.id) AS entry_count
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            WHERE a.classroom_id = ? AND l.entry_type = 'daily'
            """,
            (class_id,),
        ).fetchone()
        evaluation_row = conn.execute(
            """
            SELECT COUNT(*) AS started_count,
                   COALESCE(SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END), 0) AS draft_count,
                   COALESCE(SUM(CASE WHEN status = 'submitted' THEN 1 ELSE 0 END), 0) AS submitted_count
            FROM ojt_evaluations
            WHERE classroom_id = ? AND supervisor_id = ?
            """,
            (class_id, supervisor_id),
        ).fetchone()
    finally:
        conn.close()

    daily_average = _value(daily_row, "average_percentage", 2, None)
    return {
        "total_interns": total_interns,
        "attendance_interns": int(_value(attendance_row, "intern_count", 0, 0) or 0),
        "total_rendered_hours": float(_value(attendance_row, "total_hours", 1, 0) or 0),
        "daily_performance_interns": int(_value(daily_row, "intern_count", 0, 0) or 0),
        "daily_rating_count": int(_value(daily_row, "rating_count", 1, 0) or 0),
        "daily_performance_average": float(daily_average) if daily_average is not None else None,
        "logbook_interns": int(_value(logbook_row, "intern_count", 0, 0) or 0),
        "logbook_entry_count": int(_value(logbook_row, "entry_count", 1, 0) or 0),
        "work_interns": work_interns,
        "work_total_count": work_total_count,
        "work_reviewed_count": work_reviewed_count,
        "work_average": round(sum(work_scores) / len(work_scores), 1) if work_scores else None,
        "work_completion_average": round(sum(work_completion_rates) / len(work_completion_rates), 1) if work_completion_rates else None,
        "work_distribution": work_distribution,
        "official_started": int(_value(evaluation_row, "started_count", 0, 0) or 0),
        "official_draft": int(_value(evaluation_row, "draft_count", 1, 0) or 0),
        "official_submitted": int(_value(evaluation_row, "submitted_count", 2, 0) or 0),
    }


# ------------------------------------------------------------------ #
# Supervisor: class-wide performance insights
# ------------------------------------------------------------------ #
@classwork_ml_insights.route("/supervisor/classes/<int:class_id>/performance")
@classwork_ml_insights.route("/supervisor/classes/<int:class_id>/ml-insights")
@classwork_ml_insights.route("/supervisor/classes/<int:class_id>/insights")
@role_required("supervisor")
def supervisor_insights(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """SELECT id, supervisor_id, name, section, description, code, archived
               FROM classrooms WHERE id = ? AND supervisor_id = ?""",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
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

        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 2),
            "section": _value(classroom, "section", 3),
            "description": _value(classroom, "description", 4),
            "code": _value(classroom, "code", 5),
            "archived": _value(classroom, "archived", 6),
        }
    finally:
        conn.close()

    insights = []
    for student in students:
        student_id = int(_value(student, "id", 0))
        feedback_text = _get_latest_feedback_text(student_id, class_id)
        analysis = _safe_ml_analysis(student_id, class_id, feedback_text)
        features = analysis["features"]
        fb_analysis = analysis["feedback_analysis"]
        ml_recommendation = _build_work_recommendation(analysis)
        insights.append(
            {
                "id": student_id,
                "name": _value(student, "username", 1, "Student"),
                "email": _value(student, "email", 2, ""),
                "student_number": _value(student, "student_number", 3, ""),
                "features": features,
                "has_performance_data": analysis.get("has_performance_data", False),
                "average_percentage": features.get("average_percentage"),
                "min_percentage": features.get("min_percentage"),
                "max_percentage": features.get("max_percentage"),
                "graded_count": features.get("graded_count", 0),
                "total_count": features.get("total_count", 0),
                "completion_rate": features.get("completion_rate", 0.0),
                "manual_count": features.get("manual_count", 0),
                "imported_count": features.get("imported_count", 0),
                "numeric_performance_label": analysis.get("numeric_performance_label"),
                "performance_label": analysis.get("performance_label"),
                "feedback_analysis": fb_analysis,
                "sentiment": analysis.get("sentiment"),
                "competency": analysis.get("competency"),
                "recommendation": analysis.get("recommendation"),
                "confidence": analysis.get("confidence", 0.0),
                "has_feedback": not fb_analysis.get("is_empty", True),
                "ml_recommendation": ml_recommendation,
            }
        )

    return render_template(
        "classroom/supervisor_insights.html",
        classroom=classroom_data,
        insights=insights,
        active_page="classes",
    )


# ------------------------------------------------------------------ #
# Supervisor: cohort evidence overview
# ------------------------------------------------------------------ #
@classwork_ml_insights.route("/supervisor/classes/<int:class_id>/cohort-insights")
@role_required("supervisor")
def supervisor_cohort_insights(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """SELECT id, supervisor_id, name, section, description, code, archived
               FROM classrooms WHERE id = ? AND supervisor_id = ?""",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
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

        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 2),
            "section": _value(classroom, "section", 3),
            "description": _value(classroom, "description", 4),
            "code": _value(classroom, "code", 5),
            "archived": _value(classroom, "archived", 6),
        }
    finally:
        conn.close()

    cohort = _build_cohort_summary(class_id, supervisor_id, students)
    return render_template(
        "classroom/supervisor_cohort_insights.html",
        classroom=classroom_data,
        cohort=cohort,
        active_page="classes",
    )


# ------------------------------------------------------------------ #
# Supervisor: one intern's separate evidence dimensions
# ------------------------------------------------------------------ #
@classwork_ml_insights.route("/supervisor/classes/<int:class_id>/insights/<int:student_id>")
@role_required("supervisor")
def supervisor_individual_insights(class_id, student_id):
    supervisor_id = session["user_id"]
    profile = get_supervisor_intern_profile(
        supervisor_id=supervisor_id,
        classroom_id=class_id,
        student_id=student_id,
    )
    if not profile.get("ok"):
        abort(int(profile.get("status_code") or 404))

    evaluation_context = get_supervisor_evaluation_context(
        supervisor_id=supervisor_id,
        classroom_id=class_id,
        student_id=student_id,
    )
    if not evaluation_context.get("ok"):
        abort(int(evaluation_context.get("status_code") or 404))

    feedback_text = _get_latest_feedback_text(student_id, class_id)
    analysis = _safe_ml_analysis(student_id, class_id, feedback_text)
    features = analysis.get("features") or {}
    feedback_analysis = analysis.get("feedback_analysis") or {}
    work_recommendation = _build_work_recommendation(analysis)

    return render_template(
        "classroom/supervisor_individual_insights.html",
        classroom=profile["classroom"],
        student=profile["student"],
        attendance_summary=profile["attendance_summary"],
        daily_performance=profile["daily_performance"],
        logbook_summary=profile["logbook_summary"],
        work_summary=profile["work_summary"],
        official_evaluation=evaluation_context.get("evaluation"),
        work_features=features,
        work_performance_label=analysis.get("numeric_performance_label") or "No Performance Data",
        work_recommendation=work_recommendation,
        sentiment=analysis.get("sentiment"),
        competency=analysis.get("competency"),
        confidence=analysis.get("confidence", 0.0),
        has_feedback=not feedback_analysis.get("is_empty", True),
        active_page="classes",
    )


# ------------------------------------------------------------------ #
# Student: own performance insights only
# ------------------------------------------------------------------ #
@classwork_ml_insights.route("/student/classes/<int:class_id>/performance")
@classwork_ml_insights.route("/student/classes/<int:class_id>/ml-insights")
@classwork_ml_insights.route("/student/classes/<int:class_id>/insights")
@role_required("student")
def student_insights(class_id):
    student_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """SELECT c.id, c.name, c.section, c.supervisor_id, c.archived,
                      u.username AS supervisor_name
               FROM classrooms c
               JOIN users u ON u.id = c.supervisor_id
               JOIN classroom_students cs ON cs.classroom_id = c.id
               WHERE c.id = ? AND cs.student_id = ?""",
            (class_id, student_id),
        ).fetchone()
        if not classroom:
            abort(404)

        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 1),
            "section": _value(classroom, "section", 2),
            "supervisor": _value(classroom, "supervisor_name", 5),
            "archived": bool(_value(classroom, "archived", 4, 0)),
        }
    finally:
        conn.close()

    feedback_text = _get_latest_feedback_text(student_id, class_id)
    analysis = _safe_ml_analysis(student_id, class_id, feedback_text)
    features = analysis["features"]
    fb_analysis = analysis["feedback_analysis"]
    ml_recommendation = _build_work_recommendation(analysis)

    return render_template(
        "classroom/student_insights.html",
        classroom=classroom_data,
        features=features,
        has_performance_data=analysis.get("has_performance_data", False),
        numeric_performance_label=analysis.get("numeric_performance_label"),
        performance_label=analysis.get("performance_label"),
        feedback_analysis=fb_analysis,
        sentiment=analysis.get("sentiment"),
        competency=analysis.get("competency"),
        recommendation=analysis.get("recommendation"),
        confidence=analysis.get("confidence", 0.0),
        has_feedback=not fb_analysis.get("is_empty", True),
        average_percentage=features.get("average_percentage"),
        min_percentage=features.get("min_percentage"),
        max_percentage=features.get("max_percentage"),
        graded_count=features.get("graded_count", 0),
        total_count=features.get("total_count", 0),
        completion_rate=features.get("completion_rate", 0.0),
        manual_count=features.get("manual_count", 0),
        imported_count=features.get("imported_count", 0),
        ml_recommendation=ml_recommendation,
        active_page="classes",
    )
