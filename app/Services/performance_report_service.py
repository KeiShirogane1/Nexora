"""Thesis-ready performance report service.

Builds structured reports from existing gradebook, ML evaluation and recommendation
services without duplicating ML logic. Reuses:
- build_student_ml_analysis()
- analyze_feedback_detailed()
- build_recommendation_from_features()
"""

from app.Models.db import get_db_connection
from app.Services.classwork_ml_service import build_student_ml_analysis
from app.Services.ml_recommendation_service import build_recommendation_from_features


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
    conn = get_db_connection()
    try:
        try:
            fb = conn.execute(
                "SELECT comment FROM feedback WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
                (student_id,),
            ).fetchone()
            if fb:
                c = _value(fb, "comment", 0)
                if c and str(c).strip():
                    return str(c).strip()
        except Exception:
            pass
        try:
            sub = conn.execute(
                "SELECT feedback FROM classroom_submissions WHERE student_id = ? AND feedback IS NOT NULL AND TRIM(feedback) != '' ORDER BY submitted_at DESC LIMIT 1",
                (student_id,),
            ).fetchone()
            if sub:
                f = _value(sub, "feedback", 0)
                if f and str(f).strip():
                    return str(f).strip()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return ""


def _safe_float(v, default=None):
    try:
        if v is None:
            return default
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    except Exception:
        return default


def build_student_report(student_id, class_id, feedback_text=None):
    """
    Build a structured performance report for one student in one class.
    Handles missing/invalid data gracefully. Does not modify DB schema or auth.
    Returns dict with thesis-ready sections.
    """
    # Resolve feedback text if not provided (reuse existing logic)
    if feedback_text is None:
        feedback_text = _get_latest_feedback_text(student_id)
    feedback_text = feedback_text or ""

    # Core ML analysis (already handles invalid scores, missing assignments, missing model files)
    try:
        analysis = build_student_ml_analysis(student_id, class_id, feedback_text=feedback_text)
    except Exception:
        # Graceful fallback
        from app.ML.predictor import analyze_feedback_detailed
        from app.Services.classwork_ml_service import build_student_performance_features, classify_numeric_performance

        try:
            features = build_student_performance_features(student_id, class_id)
        except Exception:
            features = {
                "student_id": student_id,
                "class_id": class_id,
                "graded_count": 0,
                "total_count": 0,
                "average_percentage": None,
                "min_percentage": None,
                "max_percentage": None,
                "completion_rate": 0.0,
                "manual_count": 0,
                "imported_count": 0,
            }
        fa = analyze_feedback_detailed(feedback_text)
        label = classify_numeric_performance(features.get("average_percentage"))
        analysis = {
            "student_id": student_id,
            "class_id": class_id,
            "features": features,
            "numeric_performance_label": label,
            "performance_label": label,
            "feedback_analysis": fa,
            "sentiment": fa.get("sentiment"),
            "competency": fa.get("competency"),
            "recommendation": fa.get("recommendation"),
            "confidence": fa.get("confidence", 0.0),
        }

    features = analysis.get("features") or {}
    feedback_analysis = analysis.get("feedback_analysis") or {}
    numeric_label = analysis.get("numeric_performance_label") or analysis.get("performance_label") or "Satisfactory"

    # Recommendation (reuses existing service, no duplication)
    try:
        ml_reco = build_recommendation_from_features(features, feedback_analysis, performance_label=numeric_label)
    except Exception:
        ml_reco = {
            "performance_label": numeric_label,
            "overall_percentage": _safe_float(features.get("average_percentage")),
            "completion_rate": _safe_float(features.get("completion_rate"), 0.0) or 0.0,
            "recommendation": feedback_analysis.get("recommendation", "Continue monitoring performance."),
            "priority": "medium",
            "basis": [],
            "graded_count": features.get("graded_count", 0),
            "total_count": features.get("total_count", 0),
        }

    # Fetch student identity
    student = {"id": student_id, "username": "Student", "email": "", "student_number": ""}
    class_info = {"id": class_id, "name": "Class", "section": "", "code": ""}
    supervisor_info = {"id": None, "username": "", "email": ""}
    assignments = []
    strongest = None
    weakest = None

    conn = get_db_connection()
    try:
        # Student
        try:
            row = conn.execute(
                "SELECT u.id, u.username, u.email, COALESCE(p.student_id,'') AS student_number "
                "FROM users u LEFT JOIN student_profiles p ON p.user_id=u.id WHERE u.id=?",
                (student_id,),
            ).fetchone()
            if row:
                student = {
                    "id": _value(row, "id", 0, student_id),
                    "username": _value(row, "username", 1, "Student"),
                    "email": _value(row, "email", 2, ""),
                    "student_number": _value(row, "student_number", 3, ""),
                }
        except Exception:
            pass

        # Class + supervisor
        try:
            crow = conn.execute(
                "SELECT c.id, c.name, c.section, c.code, c.supervisor_id, u.username AS sup_name, u.email AS sup_email "
                "FROM classrooms c LEFT JOIN users u ON u.id=c.supervisor_id WHERE c.id=?",
                (class_id,),
            ).fetchone()
            if crow:
                class_info = {
                    "id": _value(crow, "id", 0, class_id),
                    "name": _value(crow, "name", 1, "Class"),
                    "section": _value(crow, "section", 2, ""),
                    "code": _value(crow, "code", 3, ""),
                    "supervisor_id": _value(crow, "supervisor_id", 4),
                }
                supervisor_info = {
                    "id": _value(crow, "supervisor_id", 4),
                    "username": _value(crow, "sup_name", 5, ""),
                    "email": _value(crow, "sup_email", 6, ""),
                }
        except Exception:
            pass

        # Academic performance: assignment results where safely available
        try:
            rows = conn.execute(
                """SELECT a.id, a.title, a.points, s.score, s.max_score, s.percentage, s.grading_method
                   FROM classroom_assignments a
                   LEFT JOIN classwork_scores s ON s.assignment_id=a.id AND s.student_id=?
                   WHERE a.classroom_id=?
                   ORDER BY a.created_at ASC, a.id ASC""",
                (student_id, class_id),
            ).fetchall()
            for r in rows:
                title = _value(r, "title", 1, "Assignment")
                points = _value(r, "points", 2, 0)
                score = _value(r, "score", 3)
                max_score = _value(r, "max_score", 4)
                pct = _value(r, "percentage", 5)
                method = _value(r, "grading_method", 6)
                # Skip invalid max_score
                if score is None or max_score is None:
                    # Not graded
                    assignments.append({
                        "title": title,
                        "points": _safe_float(points, 0) or 0,
                        "score": None,
                        "max_score": _safe_float(max_score) if max_score is not None else _safe_float(points, 0),
                        "percentage": None,
                        "grading_method": None,
                        "graded": False,
                    })
                    continue
                try:
                    if float(max_score or 0) <= 0:
                        continue
                except Exception:
                    continue
                # Compute pct if missing
                pct_f = _safe_float(pct)
                if pct_f is None:
                    try:
                        pct_f = float(score) / float(max_score) * 100
                    except Exception:
                        pct_f = None
                assignments.append({
                    "title": title,
                    "points": _safe_float(points, 0) or 0,
                    "score": _safe_float(score),
                    "max_score": _safe_float(max_score),
                    "percentage": pct_f,
                    "grading_method": method,
                    "graded": True,
                })
            # Strongest / weakest where safely available (among graded)
            graded_only = [a for a in assignments if a["graded"] and a["percentage"] is not None]
            if graded_only:
                strongest = max(graded_only, key=lambda x: x["percentage"])
                weakest = min(graded_only, key=lambda x: x["percentage"])
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Determine has_feedback
    has_feedback = not bool(feedback_analysis.get("is_empty", True)) if isinstance(feedback_analysis, dict) else False

    # Structured report
    report = {
        "student": student,
        "class": class_info,
        "supervisor": supervisor_info,
        "overall_percentage": _safe_float(features.get("average_percentage")),
        "completion_rate": _safe_float(features.get("completion_rate"), 0.0) or 0.0,
        "graded_count": features.get("graded_count", 0),
        "total_count": features.get("total_count", 0),
        "performance_label": numeric_label,
        "performance_classification": numeric_label,
        "feedback_analysis": feedback_analysis if has_feedback else None,
        "sentiment": feedback_analysis.get("sentiment") if has_feedback else None,
        "competency": feedback_analysis.get("competency") if has_feedback else feedback_analysis.get("competency"),
        "has_feedback": has_feedback,
        "ml_recommendation": ml_reco,
        "recommendation": ml_reco.get("recommendation"),
        "priority": ml_reco.get("priority"),
        "basis": ml_reco.get("basis", []),
        "strongest": strongest,
        "weakest": weakest,
        "assignments": assignments,
        "average_percentage": _safe_float(features.get("average_percentage")),
        "min_percentage": _safe_float(features.get("min_percentage")),
        "max_percentage": _safe_float(features.get("max_percentage")),
        "manual_count": features.get("manual_count", 0),
        "imported_count": features.get("imported_count", 0),
    }
    return report


def build_class_reports(class_id):
    """Build reports for all students in a class (supervisor view)."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT student_id FROM classroom_students WHERE classroom_id=? ORDER BY student_id",
            (class_id,),
        ).fetchall()
        student_ids = [_value(r, "student_id", 0) for r in rows]
    finally:
        try:
            conn.close()
        except Exception:
            pass
    reports = []
    for sid in student_ids:
        try:
            reports.append(build_student_report(int(sid), class_id))
        except Exception:
            # Ensure one failed student does not break whole listing
            reports.append(build_student_report(int(sid), class_id))
    return reports
