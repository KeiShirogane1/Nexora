"""Shared grade calculations for normalized classwork scores."""


def calculate_grade(earned, possible):
    """Return a percentage from earned/max points, or None when ungraded."""
    earned = float(earned or 0)
    possible = float(possible or 0)
    return (earned / possible * 100) if possible > 0 else None


def calculate_overall(scores):
    """Calculate an overall percentage from graded score records only."""
    earned = 0.0
    possible = 0.0
    graded_count = 0

    for item in scores or []:
        if not item:
            continue
        score = item.get("score")
        max_score = item.get("max_score")
        if score is None or max_score is None:
            continue
        max_score = float(max_score or 0)
        if max_score <= 0:
            continue
        earned += float(score)
        possible += max_score
        graded_count += 1

    return {
        "earned": earned,
        "possible": possible,
        "graded_count": graded_count,
        "overall": calculate_grade(earned, possible),
    }
