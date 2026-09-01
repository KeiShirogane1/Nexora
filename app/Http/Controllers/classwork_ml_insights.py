"""ML Performance Insights UI — supervisor and student views."""

from flask import Blueprint, abort, render_template, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.classwork_ml_service import (
    build_student_ml_analysis,
    build_student_performance_features,
    classify_numeric_performance,
)
from app.Services.ml_recommendation_service import build_recommendation_from_features

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


def _get_latest_feedback_text(student_id):
    """Return latest feedback comment for a student, or empty string."""
    conn = get_db_connection()
    try:
        # Primary: feedback table (supervisor evaluations)
        try:
            fb = conn.execute(
                "SELECT comment FROM feedback WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
                (student_id,),
            ).fetchone()
            if fb:
                comment = _value(fb, "comment", 0)
                if comment and str(comment).strip():
                    return str(comment).strip()
        except Exception:
            pass
        # Fallback: classroom_submissions feedback (grading comments)
        try:
            sub = conn.execute(
                "SELECT feedback FROM classroom_submissions WHERE student_id = ? AND feedback IS NOT NULL AND TRIM(feedback) != '' ORDER BY submitted_at DESC LIMIT 1",
                (student_id,),
            ).fetchone()
            if sub:
                fb2 = _value(sub, "feedback", 0)
                if fb2 and str(fb2).strip():
                    return str(fb2).strip()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return ""


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
            """SELECT id, supervisor_id, name, section, archived
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
            "archived": _value(classroom, "archived", 4),
        }
    finally:
        conn.close()

    insights = []
    for student in students:
        student_id = int(_value(student, "id", 0))
        feedback_text = _get_latest_feedback_text(student_id)
        try:
            analysis = build_student_ml_analysis(student_id, class_id, feedback_text=feedback_text)
        except Exception:
            # Fallback to features only if predictor fails
            features = build_student_performance_features(student_id, class_id)
            analysis = {
                "student_id": student_id,
                "class_id": class_id,
                "features": features,
                "numeric_performance_label": classify_numeric_performance(features.get("average_percentage")),
                "feedback_analysis": {
                    "performance_label": "Satisfactory",
                    "nb_prediction": "Satisfactory",
                    "svm_prediction": "Satisfactory",
                    "sentiment": "Neutral",
                    "competency": "Adequate Competency",
                    "recommendation": "Continue monitoring performance.",
                    "confidence": 0.0,
                    "is_empty": True,
                },
                "performance_label": classify_numeric_performance(features.get("average_percentage")),
                "sentiment": "Neutral",
                "competency": "Adequate Competency",
                "recommendation": "Continue monitoring performance.",
                "confidence": 0.0,
            }

        features = analysis["features"]
        fb_analysis = analysis["feedback_analysis"]
        # Integrated ML recommendation (numeric + feedback)
        try:
            ml_recommendation = build_recommendation_from_features(
                features, fb_analysis, performance_label=analysis.get("numeric_performance_label")
            )
        except Exception:
            ml_recommendation = {
                "performance_label": analysis.get("numeric_performance_label", "Satisfactory"),
                "overall_percentage": features.get("average_percentage"),
                "completion_rate": features.get("completion_rate", 0.0),
                "recommendation": analysis.get("recommendation", ""),
                "priority": "medium",
                "basis": [],
            }
        insights.append(
            {
                "id": student_id,
                "name": _value(student, "username", 1, "Student"),
                "email": _value(student, "email", 2, ""),
                "student_number": _value(student, "student_number", 3, ""),
                "features": features,
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

    feedback_text = _get_latest_feedback_text(student_id)
    try:
        analysis = build_student_ml_analysis(student_id, class_id, feedback_text=feedback_text)
    except Exception:
        features = build_student_performance_features(student_id, class_id)
        analysis = {
            "student_id": student_id,
            "class_id": class_id,
            "features": features,
            "numeric_performance_label": classify_numeric_performance(features.get("average_percentage")),
            "feedback_analysis": {
                "performance_label": "Satisfactory",
                "nb_prediction": "Satisfactory",
                "svm_prediction": "Satisfactory",
                "sentiment": "Neutral",
                "competency": "Adequate Competency",
                "recommendation": "Continue monitoring performance.",
                "confidence": 0.0,
                "is_empty": True,
            },
            "performance_label": classify_numeric_performance(features.get("average_percentage")),
            "sentiment": "Neutral",
            "competency": "Adequate Competency",
            "recommendation": "Continue monitoring performance.",
            "confidence": 0.0,
        }

    features = analysis["features"]
    fb_analysis = analysis["feedback_analysis"]
    try:
        ml_recommendation = build_recommendation_from_features(
            features, fb_analysis, performance_label=analysis.get("numeric_performance_label")
        )
    except Exception:
        ml_recommendation = {
            "performance_label": analysis.get("numeric_performance_label", "Satisfactory"),
            "overall_percentage": features.get("average_percentage"),
            "completion_rate": features.get("completion_rate", 0.0),
            "recommendation": analysis.get("recommendation", ""),
            "priority": "medium",
            "basis": [],
        }

    return render_template(
        "classroom/student_insights.html",
        classroom=classroom_data,
        features=features,
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
