from pathlib import Path

from app.Services import logbook_service


def test_assignment_id_normalizer_accepts_up_to_two_unique_items():
    values, error = logbook_service._normalize_assignment_ids(["11", "12", "11"])
    assert error is None
    assert values == [11, 12]


def test_assignment_id_normalizer_rejects_more_than_two_items():
    values, error = logbook_service._normalize_assignment_ids(["11", "12", "13"])
    assert values == []
    assert "up to 2" in error


def test_logbook_schema_defines_multi_work_link_table_and_legacy_backfill():
    source = Path("app/Services/logbook_service.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS daily_log_work_links" in source
    assert "PRIMARY KEY (log_id, assignment_id)" in source
    assert "related_assignment_id IS NOT NULL" in source
    assert "INSERT OR IGNORE INTO daily_log_work_links" in source


def test_daily_log_controller_reads_multiple_work_ids():
    source = Path("app/Http/Controllers/daily_logbook.py").read_text(encoding="utf-8")
    assert 'request.form.getlist("related_assignment_ids")' in source


def test_student_sidebar_enhances_work_selector_to_two_slots():
    source = Path("resources/views/components/student_sidebar.html").read_text(encoding="utf-8")
    assert "daily-related-work-secondary" in source
    assert "related_assignment_ids" in source
    assert "Choose up to 2 unfinished Work items" in source


def test_supervisor_logbook_uses_all_linked_work_items():
    source = Path("app/Services/logbook_review_service.py").read_text(encoding="utf-8")
    assert "get_logbook_work_items" in source
    assert 'entry["related_work_items"]' in source
