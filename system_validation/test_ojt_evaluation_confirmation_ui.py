from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_official_evaluation_uses_nexora_submit_confirmation():
    template = (
        ROOT / "resources/views/components/supervisor_evaluation_modal_content.html"
    ).read_text(encoding="utf-8")

    assert "Official Overall Score" in template
    assert "does not recalculate it from the criteria above" in template
    assert "data-evaluation-submit-confirm" in template
    assert "data-evaluation-submit-confirm-button" in template
    assert "Submit Official OJT Evaluation?" in template
    assert "return confirm('Submit this as the Official OJT Evaluation?" not in template
