"""Daily OJT performance rating conversion helpers.

The supervisor's original star value remains the source input. Percentages are
calculated deterministically from the approved rating anchors so controllers,
bulk actions, profiles, reports, and insights can all share one rule.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MIN_STAR_RATING = Decimal("1.0")
MAX_STAR_RATING = Decimal("5.0")
STAR_RATING_STEP = Decimal("0.1")
PERCENTAGE_PRECISION = Decimal("0.1")

# Approved anchors for the Nexora daily OJT performance scale.
# Values between anchors are linearly interpolated.
RATING_ANCHORS = (
    (Decimal("1.0"), Decimal("60.0")),
    (Decimal("2.0"), Decimal("70.0")),
    (Decimal("3.0"), Decimal("80.0")),
    (Decimal("4.0"), Decimal("90.0")),
    (Decimal("4.7"), Decimal("96.0")),
    (Decimal("5.0"), Decimal("100.0")),
)


def normalize_star_rating(value):
    """Validate and normalize a supervisor-selected 1.0-5.0 star rating."""
    try:
        rating = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, TypeError, ValueError):
        raise ValueError("Star rating must be a number from 1.0 to 5.0.")

    if not rating.is_finite():
        raise ValueError("Star rating must be a finite number from 1.0 to 5.0.")
    if rating < MIN_STAR_RATING or rating > MAX_STAR_RATING:
        raise ValueError("Star rating must be between 1.0 and 5.0.")

    normalized = rating.quantize(STAR_RATING_STEP, rounding=ROUND_HALF_UP)
    if rating != normalized:
        raise ValueError("Star rating must use 0.1-star increments.")
    return normalized


def star_rating_to_percentage(value):
    """Convert a validated star rating to its deterministic percentage."""
    rating = normalize_star_rating(value)

    for anchor_star, anchor_percentage in RATING_ANCHORS:
        if rating == anchor_star:
            return anchor_percentage.quantize(PERCENTAGE_PRECISION)

    for index in range(len(RATING_ANCHORS) - 1):
        lower_star, lower_percentage = RATING_ANCHORS[index]
        upper_star, upper_percentage = RATING_ANCHORS[index + 1]
        if lower_star < rating < upper_star:
            distance = upper_star - lower_star
            progress = (rating - lower_star) / distance
            percentage = lower_percentage + (
                progress * (upper_percentage - lower_percentage)
            )
            return percentage.quantize(
                PERCENTAGE_PRECISION,
                rounding=ROUND_HALF_UP,
            )

    raise ValueError("Star rating could not be converted.")


def build_daily_rating_snapshot(value):
    """Return storage-ready star and percentage values without inventing a grade."""
    rating = normalize_star_rating(value)
    percentage = star_rating_to_percentage(rating)
    return {
        "star_rating": float(rating),
        "percentage": float(percentage),
    }
