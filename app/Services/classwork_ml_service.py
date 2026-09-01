"""Build ML-ready student performance features from the gradebook."""

from app.Models.db import get_db_connection


def build_student_performance_features(student_id, class_id):
    """Return normalized gradebook features for one student in one class."""
    conn = get_db_connection()
    try:
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
        score = row["score"] if "score" in row.keys() else row[0]
        max_score = row["max_score"] if "max_score" in row.keys() else row[1]
        percentage = row["percentage"] if "percentage" in row.keys() else row[2]
        if score is None or max_score is None or float(max_score or 0) <= 0:
            continue
        pct = float(percentage) if percentage is not None else (float(score) / float(max_score) * 100)
        graded.append({"score": float(score), "max_score": float(max_score), "percentage": pct})

    if not graded:
        return {
            "student_id": student_id,
            "class_id": class_id,
            "graded_count": 0,
            "total_count": len(rows),
            "average_percentage": None,
            "min_percentage": None,
            "max_percentage": None,
            "completion_rate": 0.0,
            "manual_count": 0,
            "imported_count": 0,
        }

    percentages = [item["percentage"] for item in graded]
    methods = [row["grading_method"] if "grading_method" in row.keys() else row[3] for row in rows]
    return {
        "student_id": student_id,
        "class_id": class_id,
        "graded_count": len(graded),
        "total_count": len(rows),
        "average_percentage": sum(percentages) / len(percentages),
        "min_percentage": min(percentages),
        "max_percentage": max(percentages),
        "completion_rate": len(graded) / len(rows) * 100 if rows else 0.0,
        "manual_count": methods.count("manual"),
        "imported_count": methods.count("imported"),
    }
