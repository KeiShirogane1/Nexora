"""Safely remove known Nexora test/seed records.

Dry-run is the default. Nothing is deleted unless --apply is supplied.

Examples:
    python scripts/cleanup_test_data.py
    python scripts/cleanup_test_data.py --apply

The script targets unmistakable QA/test student and supervisor identities and
the classrooms owned by those identities. Admin accounts are intentionally
protected to avoid locking an installation out of its Admin portal.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.Models import db as db_module
from app.Models.db import get_db_connection, using_postgres


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TEST_USERNAME_PREFIXES = (
    "test_",
    "demo_",
    "mlsup",
    "mlstu",
    "phase6",
    "sup_owner_",
    "stu_owner_",
)

TEST_EMAIL_DOMAINS = ("@test.com", "@example.com")

# These were created by the retired scripts/seed_users.py. Common usernames
# are only considered seeds when the exact old plaintext credential remains.
LEGACY_SEED_SIGNATURES = {
    ("student", "student", "intern_123"),
    ("supervisor", "supervisor", "superv_123"),
}

CORE_TABLES = {"users", "classrooms", "classroom_assignments"}

USER_REFERENCE_COLUMNS = (
    "user_id",
    "student_id",
    "supervisor_id",
    "author_id",
    "changed_by",
)


def _quote(identifier: str) -> str:
    if not SAFE_IDENTIFIER.match(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def _chunks(values: Iterable[int], size: int = 300):
    batch = []
    for value in values:
        batch.append(int(value))
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _placeholders(count: int) -> str:
    return ",".join("?" for _ in range(count))


def _list_tables(conn) -> list[str]:
    if using_postgres():
        rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        ).fetchall()
        return [str(row[0]) for row in rows]

    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _table_columns(conn, table: str) -> set[str]:
    _quote(table)
    if using_postgres():
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = ?
            """,
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    rows = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return {str(row[1]) for row in rows}


def _is_test_user(row) -> bool:
    username = str(row[1] or "").strip()
    role = str(row[2] or "").strip().lower()
    email = str(row[3] or "").strip().lower()
    password = str(row[4] or "")

    username_lower = username.lower()

    # Never remove an Admin account from this cleanup utility. Even an old QA
    # Admin may be the only credential available on a local installation.
    if role == "admin":
        return False

    if username_lower in {"sup_test", "stu_test"}:
        return True

    if any(username_lower.startswith(prefix) for prefix in TEST_USERNAME_PREFIXES):
        return True

    if email.endswith(TEST_EMAIL_DOMAINS):
        return True

    return (username_lower, role, password) in LEGACY_SEED_SIGNATURES


def _select_test_users(conn):
    rows = conn.execute(
        "SELECT id, username, role, email, password FROM users ORDER BY id"
    ).fetchall()
    return [row for row in rows if _is_test_user(row)]


def _fetch_ids(conn, table: str, filters: list[tuple[str, list[int]]]) -> list[int]:
    if not filters:
        return []
    columns = _table_columns(conn, table)
    if "id" not in columns:
        return []

    found: set[int] = set()
    for column, ids in filters:
        if column not in columns or not ids:
            continue
        for chunk in _chunks(ids):
            sql = (
                f"SELECT id FROM {_quote(table)} "
                f"WHERE {_quote(column)} IN ({_placeholders(len(chunk))})"
            )
            for row in conn.execute(sql, tuple(chunk)).fetchall():
                found.add(int(row[0]))
    return sorted(found)


def _safe_delete_by_column(conn, table: str, column: str, ids: list[int]) -> tuple[int, str | None]:
    if not ids:
        return 0, None

    total = 0
    for chunk in _chunks(ids):
        savepoint = "nexora_seed_cleanup"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            cursor = conn.execute(
                f"DELETE FROM {_quote(table)} "
                f"WHERE {_quote(column)} IN ({_placeholders(len(chunk))})",
                tuple(chunk),
            )
            total += max(int(getattr(cursor, "rowcount", 0) or 0), 0)
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception as exc:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                pass
            return total, str(exc)
    return total, None


def _remaining_ids(conn, table: str, ids: list[int]) -> list[int]:
    if not ids:
        return []
    remaining: list[int] = []
    for chunk in _chunks(ids):
        rows = conn.execute(
            f"SELECT id FROM {_quote(table)} "
            f"WHERE id IN ({_placeholders(len(chunk))})",
            tuple(chunk),
        ).fetchall()
        remaining.extend(int(row[0]) for row in rows)
    return sorted(set(remaining))


def _print_preview(
    test_users,
    classroom_ids,
    assignment_ids,
    evaluation_ids,
    attendance_ids,
    task_ids,
):
    print("\nNexora test/seed cleanup preview")
    print("=" * 40)
    print(f"Database engine: {'PostgreSQL' if using_postgres() else 'SQLite'}")
    if not using_postgres():
        print(f"SQLite path: {db_module.SQLITE_PATH}")
    print(f"Test/seed students and supervisors: {len(test_users)}")
    print(f"Classrooms owned by test supervisors: {len(classroom_ids)}")
    print(f"Classroom assignments: {len(assignment_ids)}")
    print(f"OJT evaluations: {len(evaluation_ids)}")
    print(f"Attendance sessions: {len(attendance_ids)}")
    print(f"Legacy tasks: {len(task_ids)}")
    print("Admin accounts: protected (never deleted by this script)")

    if test_users:
        print("\nCandidate users:")
        for row in test_users[:60]:
            print(f"  id={row[0]}  role={row[2]}  username={row[1]}")
        if len(test_users) > 60:
            print(f"  ... and {len(test_users) - 60} more")

    print("\nNo data has been deleted yet.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview or remove known Nexora QA/test seed data."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the previewed test/seed records.",
    )
    args = parser.parse_args()

    conn = get_db_connection()
    try:
        tables = _list_tables(conn)
        test_users = _select_test_users(conn)
        user_ids = sorted({int(row[0]) for row in test_users})

        if not user_ids:
            print("No known Nexora test/seed users were found. Nothing to clean.")
            return 0

        classroom_ids = _fetch_ids(
            conn,
            "classrooms",
            [("supervisor_id", user_ids)],
        )
        assignment_ids = _fetch_ids(
            conn,
            "classroom_assignments",
            [("classroom_id", classroom_ids), ("author_id", user_ids)],
        )
        evaluation_ids = (
            _fetch_ids(
                conn,
                "ojt_evaluations",
                [
                    ("classroom_id", classroom_ids),
                    ("student_id", user_ids),
                    ("supervisor_id", user_ids),
                ],
            )
            if "ojt_evaluations" in tables
            else []
        )
        attendance_ids = _fetch_ids(
            conn,
            "attendance",
            [("student_id", user_ids), ("classroom_id", classroom_ids)],
        )
        task_ids = _fetch_ids(
            conn,
            "tasks",
            [("student_id", user_ids), ("supervisor_id", user_ids)],
        )

        _print_preview(
            test_users,
            classroom_ids,
            assignment_ids,
            evaluation_ids,
            attendance_ids,
            task_ids,
        )

        if not args.apply:
            print("\nRun again with --apply only after reviewing this list.")
            conn.rollback()
            return 0

        columns_by_table = {table: _table_columns(conn, table) for table in tables}

        relation_ids = {
            "evaluation_id": evaluation_ids,
            "task_id": task_ids,
            "assignment_id": assignment_ids,
            "attendance_id": attendance_ids,
            "classroom_id": classroom_ids,
        }

        deleted_rows = 0

        # Multiple passes let child rows disappear before their parents when
        # both are among the targeted test records.
        for _ in range(4):
            progress = 0
            for table in tables:
                if table in CORE_TABLES:
                    continue
                columns = columns_by_table[table]

                for column, ids in relation_ids.items():
                    if column in columns and ids:
                        count, _error = _safe_delete_by_column(
                            conn, table, column, ids
                        )
                        progress += count

                for column in USER_REFERENCE_COLUMNS:
                    if column in columns and user_ids:
                        count, _error = _safe_delete_by_column(
                            conn, table, column, user_ids
                        )
                        progress += count

            deleted_rows += progress
            if progress == 0:
                break

        # Delete the core parents only after their dependent test rows.
        count, error = _safe_delete_by_column(
            conn, "classroom_assignments", "id", assignment_ids
        )
        deleted_rows += count
        if error:
            print(f"Could not remove all classroom assignments: {error}")

        count, error = _safe_delete_by_column(
            conn, "classrooms", "id", classroom_ids
        )
        deleted_rows += count
        if error:
            print(f"Could not remove all classrooms: {error}")

        count, error = _safe_delete_by_column(conn, "users", "id", user_ids)
        deleted_rows += count
        if error:
            print(f"Could not remove all test users: {error}")

        remaining_classes = _remaining_ids(conn, "classrooms", classroom_ids)
        remaining_users = _remaining_ids(conn, "users", user_ids)

        if remaining_classes or remaining_users:
            conn.rollback()
            print("\nCleanup was rolled back for safety.")
            if remaining_classes:
                print(f"Remaining classroom IDs: {remaining_classes[:30]}")
            if remaining_users:
                print(f"Remaining user IDs: {remaining_users[:30]}")
            print(
                "A foreign-key dependency still references these records. "
                "No partial cleanup was committed."
            )
            return 1

        conn.commit()
        print(
            f"\nCleanup complete. Approximately {deleted_rows} matching rows "
            "were removed."
        )
        print(
            "Uploaded files on disk were not deleted automatically; this "
            "cleanup intentionally targets database test/seed records only."
        )
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"Cleanup failed and was rolled back: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
