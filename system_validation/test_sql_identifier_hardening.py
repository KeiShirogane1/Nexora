from app.Http.Controllers.admin_trash import _safe_delete
from app.Services import logbook_service


class _RecordingConnection:
    def __init__(self):
        self.calls = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        return []

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_admin_trash_rejects_unapproved_sql_identifiers():
    conn = _RecordingConnection()

    assert _safe_delete(conn, "users; DROP TABLE users", "id", 1) is False
    assert _safe_delete(conn, "users", "id OR 1=1", 1) is False
    assert conn.calls == []


def test_admin_trash_allows_only_registered_delete_target():
    conn = _RecordingConnection()

    assert _safe_delete(conn, "users", "id", 7) is True
    assert conn.calls[0] == ("SAVEPOINT nexora_trash_delete", None)
    assert conn.calls[1] == ("DELETE FROM users WHERE id=?", (7,))
    assert conn.calls[2] == ("RELEASE SAVEPOINT nexora_trash_delete", None)


def test_logbook_sqlite_schema_uses_fixed_alter_statements(monkeypatch):
    conn = _RecordingConnection()
    monkeypatch.setattr(logbook_service, "get_db_connection", lambda: conn)
    monkeypatch.setattr(logbook_service, "using_postgres", lambda: False)

    logbook_service.ensure_logbook_schema()

    alter_statements = [
        sql
        for sql, _params in conn.calls
        if sql.startswith("ALTER TABLE logs ADD COLUMN ")
    ]
    assert alter_statements == [
        "ALTER TABLE logs ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'activity'",
        "ALTER TABLE logs ADD COLUMN accomplishment TEXT",
        "ALTER TABLE logs ADD COLUMN reflection TEXT",
        "ALTER TABLE logs ADD COLUMN challenges TEXT",
        "ALTER TABLE logs ADD COLUMN related_assignment_id INTEGER REFERENCES classroom_assignments(id) ON DELETE SET NULL",
        "ALTER TABLE logs ADD COLUMN updated_at TIMESTAMP",
    ]
    assert conn.committed is True
    assert conn.closed is True
