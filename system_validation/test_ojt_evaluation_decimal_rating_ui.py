from pathlib import Path

from app.Services.ojt_evaluation_service import _normalize_items


ROOT = Path(__file__).resolve().parents[1]


def test_official_evaluation_supports_decimal_ratings_and_weighted_display():
    source = (ROOT / "resources/views/components/supervisor_evaluation_modal_content.html").read_text(encoding="utf-8")

    assert 'name="rating_value" min="1" max="5" step="0.01"' in source
    assert "Click a star or enter 1.00–5.00." in source
    assert "Calculated Weighted Rating" in source
    assert "data-evaluation-weighted-rating" in source
    assert "rating × weight" in source

    normalized = _normalize_items(
        [
            {
                "criterion_name": "Work Quality",
                "rating_value": "4.5",
                "max_value": "5",
                "weight": "40",
                "comments": "",
            }
        ],
        "draft",
    )

    assert normalized[0]["rating_value"] == 4.5
    assert normalized[0]["max_value"] == 5.0
    assert normalized[0]["weight"] == 40.0
