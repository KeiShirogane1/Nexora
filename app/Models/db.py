import os
import re
import sqlite3
from pathlib import Path

try:
    import psycopg2
except ImportError:
    psycopg2 = None

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SQLITE_PATH = BASE_DIR / "nexora.db"


def using_postgres():
    return bool(os.environ.get("DATABASE_URL"))


class HybridRow:
    """Row that supports both row[0] and row['column_name']."""

    def __init__(self, values, description):
        self._values = tuple(values)
        self._keys = [column[0] for column in description]
        self._mapping = dict(zip(self._keys, self._values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._mapping.keys()

    def values(self):
        return self._mapping.values()

    def items(self):
        return self._mapping.items()

    def get(self, key, default=None):
        return self._mapping.get(key, default)


class PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @staticmethod
    def _convert_placeholders(sql):
        return re.sub(r"\?", "%s", sql)

    def execute(self, sql, params=None):
        self._cursor.execute(self._convert_placeholders(sql), params or ())
        return self

    def executemany(self, sql, seq_of_params):
        self._cursor.executemany(self._convert_placeholders(sql), seq_of_params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return HybridRow(row, self._cursor.description)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [HybridRow(row, self._cursor.description) for row in rows]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        """Provide SQLite-compatible generated-id access on PostgreSQL."""
        self._cursor.execute("SELECT LASTVAL()")
        row = self._cursor.fetchone()
        return row[0] if row else None

    def close(self):
        self._cursor.close()


class PostgresConnection:
    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return PostgresCursor(self._connection.cursor())

    def execute(self, sql, params=None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def get_db_connection():
    """Return PostgreSQL on Render when DATABASE_URL exists; otherwise SQLite."""
    if using_postgres():
        if psycopg2 is None:
            raise RuntimeError(
                "DATABASE_URL is set, but psycopg2 is not installed. Run: pip install psycopg2-binary"
            )
        database_url = os.environ["DATABASE_URL"]
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]
        return PostgresConnection(psycopg2.connect(database_url))

    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
