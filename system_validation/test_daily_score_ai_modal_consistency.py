from pathlib import Path

from app.Services.ai_assistant_service import _evidence_fallback_analysis


ROOT = Path(__file__).resolve().parents[1]


def test_student_insights_exposes_daily_ojt_grade_separately_from_work():
    controller = (ROOT / "app/Http/Controllers/classwork_ml_insights.py").read_text(encoding="utf-8")
    template = (ROOT / "resources/views/classroom/student_insights.html").read_text(encoding="utf-8")

    assert "get_supervisor_daily_performance_history" in controller
    assert "daily_performance=daily_performance" in controller
    assert "Daily OJT Performance" in template
    assert "Overall Daily Rating is the numeric grade for each completed OJT day" in template
    assert "Daily OJT ratings remain the source for Internship Work analytics" in template
    assert "daily_evidence:" in template
    assert "completion: evidence.grade_coverage_percentage" in template


def test_student_ai_fallback_understands_daily_performance_without_work_score():
    result = _evidence_fallback_analysis(
        {
            "daily_evidence": True,
            "daily_average": 100.0,
            "daily_average_star": 5.0,
            "daily_rated_days": 1,
            "daily_closed_days": 2,
            "daily_latest": 100.0,
            "daily_highest": 100.0,
            "daily_lowest": 100.0,
            "work_evidence": False,
            "feedback_evidence": False,
        }
    )

    assert "100.0% (5 stars)" in result["overall"]
    assert "1 rated day(s) out of 2 completed day(s)" in result["overall"]
    assert "latest rated Daily OJT day is 100.0%" in result["happened"]
    assert "awaiting a supervisor Daily Performance rating" in result["improve"]


def test_supervisor_ai_has_evidence_fallback():
    script = (ROOT / "resources/assets/js/supervisor_insights_ai.js").read_text(encoding="utf-8")

    assert "renderEvidenceFallback(root, evidence)" in script
    assert "Live AI could not complete the response" in script
    assert "Daily Performance is already rated" in script
    assert "items.hidden = false;" in script


def test_remove_work_uses_nexora_modal_not_browser_confirm():
    template = (ROOT / "resources/views/classroom/supervisor_classwork.html").read_text(encoding="utf-8")

    assert 'id="removeWorkModal"' in template
    assert "openRemoveWorkModal(" in template
    assert 'id="confirmRemoveWorkButton"' in template
    assert "form.requestSubmit()" in template
    assert "return confirm(" not in template
    assert 'name="csrf_token"' in template
