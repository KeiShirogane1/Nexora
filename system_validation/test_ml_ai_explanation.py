from pathlib import Path

import pytest

from app.Services.ai_assistant_service import (
    AIServiceError,
    _evidence_fallback_analysis,
    _parse_ml_explanation,
)


ROOT = Path(__file__).resolve().parents[1]


def test_ml_explanation_parser_accepts_structured_json():
    result = _parse_ml_explanation(
        """```json
        {
          "overall": "Work evidence is currently satisfactory.",
          "happened": "The available Work average supports the current label.",
          "improve": "Improve the lowest-scoring Work area shown in the evidence.",
          "feedback": "Unavailable.",
          "next_focus": "Review weaker Work; complete current tasks; follow supervisor feedback"
        }
        ```"""
    )

    assert result["overall"] == "Work evidence is currently satisfactory."
    assert result["feedback"] == "Unavailable."
    assert ";" in result["next_focus"]


def test_ml_explanation_parser_fills_missing_fields_without_prompt_text():
    result = _parse_ml_explanation('{"overall":"Current evidence is limited."}')

    assert result["overall"] == "Current evidence is limited."
    assert result["happened"] == "Unavailable."
    assert result["improve"] == "Unavailable."
    assert result["feedback"] == "Unavailable."
    assert result["next_focus"] == "Unavailable."


def test_ml_explanation_parser_rejects_instruction_leakage():
    with pytest.raises(AIServiceError):
        _parse_ml_explanation(
            '{"overall":"Okay","happened":"Okay","improve":"Okay",'
            '"feedback":"Unavailable.","next_focus":"For NEXT FOCUS give 2-4 actions separated by semicolons."}'
        )


def test_ml_evidence_fallback_uses_only_supplied_current_values():
    result = _evidence_fallback_analysis(
        {
            "work_evidence": True,
            "average": 67.0,
            "minimum": 67.0,
            "maximum": 67.0,
            "completion": 33.3,
            "reviewed": 1,
            "total": 3,
            "work_label": "Fair",
            "work_recommendation": "Review current Work and seek supervisor guidance.",
            "priority": "High",
            "feedback_evidence": False,
        }
    )

    assert "1 of 3" in result["overall"]
    assert "67.0%" in result["overall"]
    assert "Fair" in result["overall"]
    assert "33.3%" in result["happened"]
    assert result["improve"] == "Review current Work and seek supervisor guidance."
    assert result["feedback"] == "Unavailable."
    assert "not yet reviewed" in result["next_focus"]


def test_student_insights_uses_structured_ml_explanation_endpoint():
    template = (ROOT / "resources/views/classroom/student_insights.html").read_text(encoding="utf-8")

    assert "fetch('/assistant/ml-explanation'" in template
    assert "body: JSON.stringify({evidence: aiEvidence})" in template
    assert "nxMlAiAnalysis:v4:" in template
    assert "renderAnalysis(data.analysis)" in template
    assert "parseAnswer(data.answer)" not in template
    assert "Return exactly five concise labeled sections" not in template
    assert "For NEXT FOCUS give 2-4 actions" not in template


def test_ml_explanation_service_limits_latency_and_keeps_fallback():
    service = (ROOT / "app/Services/ai_assistant_service.py").read_text(encoding="utf-8")

    assert "max_tokens=240" in service
    assert "timeout_seconds=8" in service
    assert 'source = "evidence_fallback"' in service
    assert "_evidence_fallback_analysis(clean_evidence)" in service


def test_ml_explanation_route_is_login_protected_and_dedicated():
    controller = (ROOT / "app/Http/Controllers/assistant.py").read_text(encoding="utf-8")

    assert '@assistant_bp.route("/assistant/ml-explanation", methods=["POST"])' in controller
    route_index = controller.index('@assistant_bp.route("/assistant/ml-explanation"')
    protected_index = controller.index("@login_required", route_index)
    handler_index = controller.index("def ml_explanation():", protected_index)
    assert route_index < protected_index < handler_index
    assert "explain_ml_evidence(session.get(\"user_id\"), evidence)" in controller


def test_supervisor_insights_registers_assistant_and_matches_export_buttons():
    bootstrap = (ROOT / "bootstrap/app.py").read_text(encoding="utf-8")
    script = (ROOT / "resources/assets/js/supervisor_insights_ai.js").read_text(encoding="utf-8")
    template = (ROOT / "resources/views/classroom/supervisor_individual_insights.html").read_text(encoding="utf-8")

    assert "from app.Http.Controllers.assistant import assistant_bp" in bootstrap
    assert "supervisor_profile_photo,assistant_bp,notifications_bp,messages" in bootstrap
    assert "url_for('assistant.ask')" in template
    assert "url_for('assistant_bp.ask')" not in template
    assert 'ensureExportLink(controls, "pdf", `/supervisor/classes/${classId}/insights/export.pdf`, false);' in script
    assert 'pdfLink.className = "btn btn-sm btn-outline-primary";' in script
