"""Build ML-ready student performance features and analysis inputs."""

from app.Models.db import get_db_connection
from app.Services.classwork_grade_calculator import calculate_overall
from app.ML.predictor import analyze_feedback_detailed


def _value(row, key, index=0, default=None):
    try:
        if key in row.keys():
            return row[key]
    except AttributeError:
        pass
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return default


def build_student_performance_features(student_id, class_id):
    """Return normalized gradebook features for one student in one class."""
    conn = get_db_connection()
    try:
        assignment_row = conn.execute(
            "SELECT COUNT(*) AS total_assignments FROM classroom_assignments WHERE classroom_id = ?",
            (class_id,),
        ).fetchone()
        total_assignments = int(_value(assignment_row, "total_assignments", 0, 0) or 0)

        rows = conn.execute(
            """SELECT s.score, s.max_score, s.percentage, s.grading_method
               FROM classwork_scores s
               JOIN classroom_assignments a ON a.id = s.assignment_id
               WHERE s.student_id = ? AND a.classroom_id = ?
               ORDER BY a.created_at ASC, a.id ASC""",
            (student_id, class_id),
        ).fetchall()
    finally:
        conn.close()

    graded = []
    for row in rows:
        score = _value(row, "score", 0)
        max_score = _value(row, "max_score", 1)
        percentage = _value(row, "percentage", 2)
        if score is None or max_score is None or float(max_score or 0) <= 0:
            continue
        pct = float(percentage) if percentage is not None else (float(score) / float(max_score) * 100)
        graded.append({"score": float(score), "max_score": float(max_score), "percentage": pct})

    methods = [_value(row, "grading_method", 3) for row in rows]
    if not graded:
        return {
            "student_id": student_id,
            "class_id": class_id,
            "graded_count": 0,
            "total_count": total_assignments,
            "average_percentage": None,
            "min_percentage": None,
            "max_percentage": None,
            "completion_rate": 0.0,
            "manual_count": methods.count("manual"),
            "imported_count": methods.count("imported"),
        }

    percentages = [item["percentage"] for item in graded]
    return {
        "student_id": student_id,
        "class_id": class_id,
        "graded_count": len(graded),
        "total_count": total_assignments,
        "average_percentage": sum(percentages) / len(percentages),
        "min_percentage": min(percentages),
        "max_percentage": max(percentages),
        "completion_rate": len(graded) / total_assignments * 100 if total_assignments else 0.0,
        "manual_count": methods.count("manual"),
        "imported_count": methods.count("imported"),
    }


def classify_numeric_performance(average_percentage):
    """Map numeric gradebook performance to the thesis performance labels."""
    if average_percentage is None:
        return "Satisfactory"
    score = float(average_percentage)
    if score >= 90:
        return "Excellent"
    if score >= 85:
        return "Very Satisfactory"
    if score >= 75:
        return "Satisfactory"
    if score >= 60:
        return "Fair"
    return "Needs Improvement"


def build_student_ml_analysis(student_id, class_id, feedback_text=""):
    """Combine normalized gradebook metrics with the existing feedback ML analysis."""
    features = build_student_performance_features(student_id, class_id)
    numeric_label = classify_numeric_performance(features["average_percentage"])
    feedback_analysis = analyze_feedback_detailed(feedback_text)

    return {
        "student_id": student_id,
        "class_id": class_id,
        "features": features,
        "numeric_performance_label": numeric_label,
        "feedback_analysis": feedback_analysis,
        "performance_label": numeric_label if not feedback_analysis["is_empty"] else numeric_label,
        "sentiment": feedback_analysis["sentiment"],
        "competency": feedback_analysis["competency"],
        "recommendation": feedback_analysis["recommendation"],
        "confidence": feedback_analysis["confidence"],
    }
