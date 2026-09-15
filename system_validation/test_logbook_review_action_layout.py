from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_logbook_review_separates_approval_from_other_actions():
    source = (ROOT / "resources/views/classroom/supervisor_logbook_review.html").read_text(encoding="utf-8")

    assert '.ojt-review-footer .ojt-footer-button[value="approved"] { order:4; margin-left:auto; }' in source
    assert '.ojt-review-footer .ojt-footer-button[form="ojt-individual-rating-form"] { order:3; }' in source
    assert 'value="revision_requested">Request Revision</button>' in source
    assert 'value="reviewed">Mark Reviewed</button>' in source
    assert 'value="approved">Approve Entry</button>' in source

    approve_rule = source.index('.ojt-review-footer .ojt-footer-button[value="approved"]')
    rating_rule = source.index('.ojt-review-footer .ojt-footer-button[form="ojt-individual-rating-form"]')
    assert rating_rule < approve_rule
