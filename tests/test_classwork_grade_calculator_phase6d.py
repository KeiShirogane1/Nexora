from app.Services.classwork_grade_calculator import calculate_grade, calculate_overall


def test_calculate_grade_returns_percentage():
    assert calculate_grade(45, 50) == 90.0


def test_calculate_grade_returns_none_without_possible_points():
    assert calculate_grade(10, 0) is None


def test_calculate_overall_uses_graded_work_only():
    result = calculate_overall([
        {"score": 80, "max_score": 100},
        {"score": 45, "max_score": 50},
        {"score": None, "max_score": 20},
    ])
    assert result["earned"] == 125.0
    assert result["possible"] == 150.0
    assert result["graded_count"] == 2
    assert round(result["overall"], 2) == 83.33


def test_calculate_overall_ignores_invalid_max_score():
    result = calculate_overall([
        {"score": 90, "max_score": 100},
        {"score": 10, "max_score": 0},
    ])
    assert result["graded_count"] == 1
    assert result["overall"] == 90.0


def test_calculate_overall_empty_returns_ungraded():
    result = calculate_overall([])
    assert result == {
        "earned": 0.0,
        "possible": 0.0,
        "graded_count": 0,
        "overall": None,
    }
