"""ML Recommendation Integration — deterministic, explainable recommendations
based on BOTH gradebook performance and ML feedback classification.

Reuses existing predictor output via classwork_ml_service.build_student_ml_analysis
and does NOT duplicate ML logic.
"""

from app.ML.predictor import analyze_feedback_detailed
from app.Services.classwork_ml_service import build_student_ml_analysis, classify_numeric_performance


# Label-specific recommendation templates (contain thesis-required phrases)
_RECOMMENDATION_TEMPLATES = {
    "Excellent": (
        "Excellent — maintaining performance, advanced/challenging tasks, peer support/leadership. "
        "Maintain excellent performance, pursue advanced and challenging tasks, "
        "and support peers through leadership or mentoring."
    ),
    "Very Satisfactory": (
        "Very Satisfactory — maintaining consistency and improving weaker areas to reach excellent. "
        "Maintain consistency and focus on improving weaker areas."
    ),
    "Satisfactory": (
        "Satisfactory — targeted practice and improvement on lower-scoring work; "
        "review weaker assignments and ensure consistent completion. Targeted practice and improvement on lower-scoring work."
    ),
    "Fair": (
        "Fair — focused remediation, reviewing missed/weak tasks, and supervisor guidance. "
        "Focused remediation: review missed or weak tasks, seek supervisor guidance, "
        "and improve consistency, communication, and time management."
    ),
    "Needs Improvement": (
        "Needs Improvement — immediate targeted support, reviewing fundamentals, "
        "completing missing/weak work, and supervisor follow-up. Immediate targeted support: review fundamentals, "
        "complete missing or weak work, and schedule supervisor follow-up with a structured improvement plan. "
        "Completing missing/weak work and reviewing fundamentals."
    ),
}

_PRIORITY_MAP = {
    "Excellent": "low",
    "Very Satisfactory": "low",
    "Satisfactory": "medium",
    "Fair": "high",
    "Needs Improvement": "critical",
}

_VALID_LABELS = {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        f = float(value)
        # handle NaN/inf
        if f != f or f == float("inf") or f == float("-inf"):
            return default
        return f
    except Exception:
        return default


def _build_basis(performance_label, features, feedback_analysis):
    """Explainable basis for recommendation — deterministic list of strings."""
    basis = []
    # Gradebook basis
    if features is not None:
        graded = features.get("graded_count")
        total = features.get("total_count")
        avg = features.get("average_percentage")
        comp = features.get("completion_rate")
        min_pct = features.get("min_percentage")
        max_pct = features.get("max_percentage")

        if graded is not None and total is not None:
            try:
                basis.append(f"gradebook: {int(graded)}/{int(total)} graded")
            except Exception:
                basis.append(f"gradebook: {graded}/{total} graded")
        if comp is not None:
            c = _safe_float(comp)
            if c is not None:
                basis.append(f"completion rate: {c:.1f}%")
        if avg is not None:
            a = _safe_float(avg)
            if a is not None:
                basis.append(f"overall percentage: {a:.1f}%")
        # strongest/weakest where safely available (need at least 1 graded)
        graded_int = _safe_float(graded, 0) or 0
        if graded_int and graded_int > 0:
            mn = _safe_float(min_pct)
            mx = _safe_float(max_pct)
            if mn is not None and mx is not None:
                basis.append(f"strongest {mx:.1f}%, weakest {mn:.1f}%")
            elif mn is not None:
                basis.append(f"weakest {mn:.1f}%")
            elif mx is not None:
                basis.append(f"strongest {mx:.1f}%")
        # incomplete work cue
        try:
            if total is not None and graded is not None and int(total) > int(graded):
                basis.append(f"incomplete work: {int(total) - int(graded)} assignment(s) missing")
            elif total is not None and int(total) == 0:
                basis.append("no assignments in this class")
            elif graded == 0:
                basis.append("no grades yet")
        except Exception:
            pass
    # ML basis
    if feedback_analysis is not None:
        is_empty = feedback_analysis.get("is_empty", True)
        ml_label = feedback_analysis.get("performance_label")
        if not is_empty and ml_label:
            basis.append(f"feedback ML classification: {ml_label}")
            # include sentiment/competency if present for explainability, but not required for student privacy
            sentiment = feedback_analysis.get("sentiment")
            if sentiment:
                basis.append(f"sentiment: {sentiment}")
        else:
            basis.append("no feedback text available — recommendation based on gradebook only")
    else:
        basis.append("no feedback analysis available")

    # Always include performance label basis
    basis.insert(0, f"performance label: {performance_label}")
    return basis


def _recommendation_text(performance_label, features, feedback_analysis):
    """Build deterministic recommendation string with numeric context."""
    base = _RECOMMENDATION_TEMPLATES.get(performance_label, _RECOMMENDATION_TEMPLATES["Satisfactory"])
    parts = [base]

    if features is not None:
        avg = _safe_float(features.get("average_percentage"))
        comp = _safe_float(features.get("completion_rate"))
        graded = features.get("graded_count")
        total = features.get("total_count")
        min_pct = _safe_float(features.get("min_percentage"))
        max_pct = _safe_float(features.get("max_percentage"))

        # Add numeric context where safely available
        if avg is not None:
            parts.append(f" Overall {avg:.1f}% across {graded}/{total} graded assignments.")
        if comp is not None and comp < 100:
            try:
                missing = int(total) - int(graded) if total is not None and graded is not None else 0
                if missing > 0:
                    parts.append(f" Completion {comp:.1f}% — {missing} assignment(s) still missing or weak; prioritize completing them.")
                else:
                    parts.append(f" Completion {comp:.1f}% — review weaker work to improve consistency.")
            except Exception:
                parts.append(f" Completion {comp:.1f}%.")
        # strongest/weakest hint - handle invalid graded safely
        try:
            graded_int = int(graded) if graded is not None and str(graded).strip().lstrip("-").isdigit() else _safe_float(graded, 0) or 0
            if graded_int > 0 and min_pct is not None and max_pct is not None and min_pct != max_pct:
                parts.append(f" Strongest {max_pct:.1f}%, weakest {min_pct:.1f}% — focus on the weakest to raise the overall.")
        except Exception:
            pass
        # Edge: no assignments
        try:
            total_int = _safe_float(total, None)
            graded_int2 = _safe_float(graded, 0) or 0
            if total is not None and total_int == 0:
                parts.append(" No assignments have been created for this class yet.")
            elif graded_int2 == 0:
                parts.append(" No grades recorded yet — complete upcoming work to establish a baseline.")
        except Exception:
            pass
    # Feedback cue (reuse predictor's recommendation only as basis, not duplication)
    if feedback_analysis is not None and not feedback_analysis.get("is_empty", True):
        # Already incorporated via basis; keep text focused on gradebook + label
        pass

    return "".join(parts)


def build_recommendation(student_id, class_id, feedback_text=""):
    """
    Primary entry: builds structured recommendation for a student in a class.
    Handles edge cases gracefully (no assignments, no grades, no feedback, invalid scores, missing model files).
    Returns dict with performance_label, overall_percentage, completion_rate, recommendation, priority, basis
    plus additional context for UI (graded_count, total_count, min/max, etc.).
    """
    # Use existing service to avoid duplicating logic; handle invalid data safely
    try:
        analysis = build_student_ml_analysis(student_id, class_id, feedback_text or "")
    except Exception:
        # Fallback to safe defaults if analysis fails (e.g., DB error, invalid ids)
        analysis = {
            "features": {
                "average_percentage": None,
                "min_percentage": None,
                "max_percentage": None,
                "graded_count": 0,
                "total_count": 0,
                "completion_rate": 0.0,
                "manual_count": 0,
                "imported_count": 0,
            },
            "numeric_performance_label": "Satisfactory",
            "feedback_analysis": analyze_feedback_detailed(feedback_text or ""),
            "performance_label": "Satisfactory",
        }
        # Ensure numeric label from features if possible
        try:
            avg = analysis["features"].get("average_percentage")
            analysis["numeric_performance_label"] = classify_numeric_performance(avg)
            analysis["performance_label"] = analysis["numeric_performance_label"]
        except Exception:
            pass

    features = analysis.get("features") or {}
    # Prefer numeric performance label (gradebook-driven) as primary; it is deterministic and thesis-aligned
    performance_label = analysis.get("numeric_performance_label") or analysis.get("performance_label") or "Satisfactory"
    if performance_label not in _VALID_LABELS:
        performance_label = "Satisfactory"

    feedback_analysis = analysis.get("feedback_analysis") or analyze_feedback_detailed(feedback_text or "")

    overall = _safe_float(features.get("average_percentage"))
    completion = _safe_float(features.get("completion_rate"), 0.0)
    if completion is None:
        completion = 0.0

    recommendation = _recommendation_text(performance_label, features, feedback_analysis)
    priority = _PRIORITY_MAP.get(performance_label, "medium")
    basis = _build_basis(performance_label, features, feedback_analysis)

    # Structured output — minimal but thesis-ready, does not expose internal model weights
    return {
        "performance_label": performance_label,
        "overall_percentage": overall,
        "completion_rate": float(completion),
        "graded_count": features.get("graded_count", 0),
        "total_count": features.get("total_count", 0),
        "min_percentage": _safe_float(features.get("min_percentage")),
        "max_percentage": _safe_float(features.get("max_percentage")),
        "manual_count": features.get("manual_count", 0),
        "imported_count": features.get("imported_count", 0),
        "recommendation": recommendation,
        "priority": priority,
        "basis": basis,
        "has_feedback": not bool(feedback_analysis.get("is_empty", True)),
        "feedback_label": feedback_analysis.get("performance_label"),
        "sentiment": feedback_analysis.get("sentiment"),
    }


# Pure helper for tests that want to drive recommendation from explicit features without DB
def build_recommendation_from_features(features, feedback_analysis=None, performance_label=None):
    """Deterministic helper for unit tests — builds recommendation from given features and feedback analysis."""
    if feedback_analysis is None:
        feedback_analysis = analyze_feedback_detailed("")
    if performance_label is None:
        avg = None
        try:
            avg = features.get("average_percentage") if features else None
        except Exception:
            avg = None
        try:
            performance_label = classify_numeric_performance(avg)
        except Exception:
            performance_label = "Satisfactory"
    if performance_label not in _VALID_LABELS:
        performance_label = "Satisfactory"
    if features is None:
        features = {
            "average_percentage": None,
            "min_percentage": None,
            "max_percentage": None,
            "graded_count": 0,
            "total_count": 0,
            "completion_rate": 0.0,
            "manual_count": 0,
            "imported_count": 0,
        }
    overall = _safe_float(features.get("average_percentage"))
    completion = _safe_float(features.get("completion_rate"), 0.0) or 0.0
    recommendation = _recommendation_text(performance_label, features, feedback_analysis)
    priority = _PRIORITY_MAP.get(performance_label, "medium")
    basis = _build_basis(performance_label, features, feedback_analysis)
    return {
        "performance_label": performance_label,
        "overall_percentage": overall,
        "completion_rate": float(completion),
        "graded_count": features.get("graded_count", 0),
        "total_count": features.get("total_count", 0),
        "min_percentage": _safe_float(features.get("min_percentage")),
        "max_percentage": _safe_float(features.get("max_percentage")),
        "manual_count": features.get("manual_count", 0),
        "imported_count": features.get("imported_count", 0),
        "recommendation": recommendation,
        "priority": priority,
        "basis": basis,
        "has_feedback": not bool(feedback_analysis.get("is_empty", True)),
        "feedback_label": feedback_analysis.get("performance_label"),
        "sentiment": feedback_analysis.get("sentiment"),
    }


# Aliases for flexibility — tests may import different names
get_recommendation = build_recommendation
generate_recommendation = build_recommendation
build_ml_recommendation = build_recommendation
get_ml_recommendation = build_recommendation
