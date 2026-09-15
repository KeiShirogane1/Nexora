from pathlib import Path

import pytest

from app.Services.ai_assistant_service import AIServiceError, _parse_ml_explanation


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


def test_student_insights_uses_structured_ml_explanation_endpoint():
    template = (ROOT / "resources/views/classroom/student_insights.html").read_text(encoding="utf-8")

    assert "fetch('/assistant/ml-explanation'" in template
    assert "body: JSON.stringify({evidence: aiEvidence})" in template
    assert "nxMlAiAnalysis:v2:" in template
    assert "renderAnalysis(data.analysis)" in template
    assert "parseAnswer(data.answer)" not in template
    assert "Return exactly five concise labeled sections" not in template
    assert "For NEXT FOCUS give 2-4 actions" not in template


def test_ml_explanation_route_is_login_protected_and_dedicated():
    controller = (ROOT / "app/Http/Controllers/assistant.py").read_text(encoding="utf-8")

    assert '@assistant_bp.route("/assistant/ml-explanation", methods=["POST"])' in controller
    route_index = controller.index('@assistant_bp.route("/assistant/ml-explanation"')
    protected_index = controller.index("@login_required", route_index)
    handler_index = controller.index("def ml_explanation():", protected_index)
    assert route_index < protected_index < handler_index
    assert "explain_ml_evidence(session.get(\"user_id\"), evidence)" in controller
