from unittest.mock import MagicMock, patch

from app.Services import performance_rating_service as rating_service


def _cursor(*, one=None, many=None):
    cursor = MagicMock()
    cursor.fetchone.return_value = one
    cursor.fetchall.return_value = many or []
    return cursor


def test_linked_assignments_returns_every_phase2_work_link():
    conn = MagicMock()

    def execute(sql, params=None):
        normalized = " ".join(sql.split())
        if "JOIN daily_log_work_links link" in normalized:
            return _cursor(many=[{"assignment_id": 11}, {"assignment_id": 14}])
        raise AssertionError(f"Unexpected SQL: {normalized}")

    conn.execute.side_effect = execute

    assert rating_service._linked_assignments_for_attendance(conn, 7, 3) == [11, 14]


def test_linked_assignments_keeps_legacy_first_link_fallback():
    conn = MagicMock()
    calls = []

    def execute(sql, params=None):
        normalized = " ".join(sql.split())
        calls.append(normalized)
        if "JOIN daily_log_work_links link" in normalized:
            return _cursor(many=[])
        if "SELECT related_assignment_id FROM logs" in normalized:
            return _cursor(one={"related_assignment_id": 21})
        raise AssertionError(f"Unexpected SQL: {normalized}")

    conn.execute.side_effect = execute

    assert rating_service._linked_assignments_for_attendance(conn, 7, 3) == [21]
    assert len(calls) == 2


def test_one_daily_rating_syncs_every_linked_work():
    conn = MagicMock()

    with patch.object(
        rating_service,
        "_linked_assignments_for_attendance",
        return_value=[31, 32],
    ), patch.object(rating_service, "_sync_work_score_from_daily_ratings") as sync_work:
        rating_service._sync_attendance_work_score(conn, 9, 5, now="stamp")

    assert sync_work.call_count == 2
    sync_work.assert_any_call(conn, 31, 5, now="stamp")
    sync_work.assert_any_call(conn, 32, 5, now="stamp")


def test_daily_rating_schema_prepares_multi_criterion_storage():
    source = open("app/Services/performance_rating_service.py", encoding="utf-8").read()

    assert "CREATE TABLE IF NOT EXISTS daily_performance_rating_items" in source
    assert "criterion_key" in source
    assert "criterion_name" in source
    assert "rating_value" in source
    assert "max_value" in source


def test_work_score_average_uses_phase2_links_and_legacy_fallback():
    source = open("app/Services/performance_rating_service.py", encoding="utf-8").read()

    assert "JOIN daily_log_work_links link ON link.log_id = l.id" in source
    assert "l.related_assignment_id = ?" in source
    assert "AVG(r.percentage)" in source
