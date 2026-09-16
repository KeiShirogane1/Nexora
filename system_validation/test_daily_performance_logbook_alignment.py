from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_daily_performance_history_requires_existing_daily_logbook():
    source = _read("app/Services/daily_performance_history_service.py")
    start = source.index("def _attendance_history_rows")
    end = source.index("def get_supervisor_daily_performance_history", start)
    history_query = source[start:end]

    assert "JOIN logs l" in history_query
    assert "LEFT JOIN logs l" not in history_query
    assert "l.attendance_id = a.id" in history_query
    assert "l.student_id = a.student_id" in history_query
    assert "l.entry_type = 'daily'" in history_query
    assert "LEFT JOIN daily_performance_ratings dpr" in history_query


def test_daily_performance_history_still_preserves_unrated_existing_logbooks():
    source = _read("app/Services/daily_performance_history_service.py")

    assert 'is_rated = raw_star is not None and raw_percentage is not None' in source
    assert '"log_id": _row_value(row, "log_id", 3, None)' in source
    assert '"is_rated": is_rated' in source
