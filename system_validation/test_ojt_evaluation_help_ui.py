from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_official_evaluation_help_icons_and_draft_summary():
    directory = (ROOT / "resources/views/supervisor/evaluations.html").read_text(encoding="utf-8")
    modal = (ROOT / "resources/views/components/supervisor_evaluation_modal_content.html").read_text(encoding="utf-8")

    assert "<span>Draft</span>" in directory
    assert "<span>For Review</span>" not in directory
    assert "{{ summary.for_review }}" in directory
    assert "Rating help: Click a star for a whole-number rating or enter an exact decimal rating from 1.00 to 5.00" in modal
    assert "All weights must total 100%; Nexora automatically calculates the last criterion weight." in modal
    assert modal.count('<svg width="16" height="16"') >= 2
    assert "ⓘ" not in modal
