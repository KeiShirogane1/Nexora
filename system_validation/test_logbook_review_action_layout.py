from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_logbook_review_separates_approval_from_other_actions():
    source = (ROOT / "resources/views/classroom/supervisor_logbook_review.html").read_text(encoding="utf-8")
    css = (ROOT / "resources/assets/css/supervisor.css").read_text(encoding="utf-8")

    assert ".ojt-footer-actions { display:flex;" in css
    assert ".ojt-footer-actions.is-primary { margin-left:auto; }" in css
    assert "<style" not in source.lower()
    assert 'class="ojt-footer-actions"' in source
    assert 'class="ojt-footer-actions is-primary"' in source
    assert 'value="revision_requested">Request Revision</button>' in source
    assert 'value="reviewed">Mark Reviewed</button>' in source
    assert 'value="approved">Approve Entry</button>' in source

    rating_button = source.index(
        'class="ojt-footer-button primary" type="submit" form="ojt-individual-rating-form"'
    )
    approve_button = source.index(
        'class="ojt-footer-button primary" type="submit" form="ojt-individual-review-form" name="status" value="approved"'
    )
    assert rating_button < approve_button
