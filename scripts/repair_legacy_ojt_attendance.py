"""Preview or repair legacy OJT attendance that has no Intern Classroom scope.

Dry-run is the default. Nothing is updated unless --apply is supplied.

Examples:
    python scripts/repair_legacy_ojt_attendance.py
    python scripts/repair_legacy_ojt_attendance.py --apply
    python scripts/repair_legacy_ojt_attendance.py --user-id 12
    python scripts/repair_legacy_ojt_attendance.py --user-id 12 --classroom-id 8
    python scripts/repair_legacy_ojt_attendance.py --user-id 12 --classroom-id 8 --apply

Automatic repair is intentionally conservative:
- attendance must currently have classroom_id IS NULL
- the student must have an Intern Classroom membership
- a unique legacy supervisor match wins when one exists
- otherwise exactly one Intern Classroom membership is required
- conflicting or ambiguous supervisor/classroom evidence is never guessed

Assigning attendance.classroom_id is sufficient for its existing logs because logs
already point to attendance through logs.attendance_id.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.Models import db as db_module
from app.Models.db import get_db_connection, using_postgres


def _row_value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except AttributeError:
        pass
    try:
        value = row[index]
        return default if value is None else value
    except (IndexError, KeyError, TypeError):
        return default


def _table_exists(conn, table: str) -> bool:
    if using_postgres():
        row = conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ?
              AND table_type = 'BASE TABLE'
            LIMIT 1
            """,
            (table,),
        ).fetchone()
        return row is not None

    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        LIMIT 1
        """,
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn, table: str) -> set[str]:
    if using_postgres():
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ?
            """,
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _require_current_schema(conn) -> None:
    required_tables = {
        "users",
        "attendance",
        "logs",
        "classrooms",
        "classroom_students",
    }
    missing_tables = [table for table in sorted(required_tables) if not _table_exists(conn, table)]
    if missing_tables:
        raise RuntimeError(
            "Missing required table(s): "
            + ", ".join(missing_tables)
            + ". Start Nexora once so its current additive schema setup can run."
        )

    attendance_columns = _table_columns(conn, "attendance")
    classroom_columns = _table_columns(conn, "classrooms")
    if "classroom_id" not in attendance_columns:
        raise RuntimeError(
            "attendance.classroom_id is missing. Start Nexora once so "
            "ensure_attendance_schema() can run before using this repair."
        )
    if "classroom_type" not in classroom_columns:
        raise RuntimeError(
            "classrooms.classroom_type is missing. Start Nexora once so "
            "ensure_classroom_schema() can run before using this repair."
        )


def _legacy_attendance(conn, user_id: int | None):
    sql = """
        SELECT
            a.id,
            a.student_id,
            a.clock_in,
            a.clock_out,
            a.hours_rendered,
            a.status,
            COUNT(l.id) AS log_count,
            u.username,
            u.email
        FROM attendance a
        JOIN users u ON u.id = a.student_id
        LEFT JOIN logs l ON l.attendance_id = a.id
        WHERE a.classroom_id IS NULL
    """
    params = []
    if user_id is not None:
        sql += " AND a.student_id = ?"
        params.append(user_id)
    sql += """
        GROUP BY
            a.id,
            a.student_id,
            a.clock_in,
            a.clock_out,
            a.hours_rendered,
            a.status,
            u.username,
            u.email
        ORDER BY a.student_id, a.clock_in, a.id
    """
    return conn.execute(sql, tuple(params)).fetchall()


def _intern_classrooms(conn, student_id: int):
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.supervisor_id,
            c.name,
            c.section,
            COALESCE(c.archived, 0) AS archived,
            cs.joined_at
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        WHERE cs.student_id = ?
          AND COALESCE(c.classroom_type, 'classroom') = 'internship'
        ORDER BY COALESCE(c.archived, 0) ASC, cs.joined_at DESC, c.id DESC
        """,
        (student_id,),
    ).fetchall()
    return [
        {
            "id": int(_row_value(row, "id", 0, 0)),
            "supervisor_id": int(_row_value(row, "supervisor_id", 1, 0)),
            "name": str(_row_value(row, "name", 2, "Intern Classroom") or "Intern Classroom"),
            "section": str(_row_value(row, "section", 3, "") or ""),
            "archived": bool(_row_value(row, "archived", 4, 0)),
            "joined_at": _row_value(row, "joined_at", 5, None),
        }
        for row in rows
    ]


def _legacy_supervisor_evidence(conn, student_id: int) -> dict[int, set[str]]:
    evidence: dict[int, set[str]] = defaultdict(set)

    if _table_exists(conn, "internships"):
        columns = _table_columns(conn, "internships")
        if {"student_id", "supervisor_id"}.issubset(columns):
            rows = conn.execute(
                """
                SELECT DISTINCT supervisor_id
                FROM internships
                WHERE student_id = ? AND supervisor_id IS NOT NULL
                """,
                (student_id,),
            ).fetchall()
            for row in rows:
                try:
                    evidence[int(row[0])].add("internships")
                except (TypeError, ValueError):
                    continue

    if _table_exists(conn, "student_assignments"):
        columns = _table_columns(conn, "student_assignments")
        if {"student_id", "supervisor_id"}.issubset(columns):
            rows = conn.execute(
                """
                SELECT DISTINCT supervisor_id
                FROM student_assignments
                WHERE student_id = ? AND supervisor_id IS NOT NULL
                """,
                (student_id,),
            ).fetchall()
            for row in rows:
                try:
                    evidence[int(row[0])].add("student_assignments")
                except (TypeError, ValueError):
                    continue

    return evidence


def _infer_target(classrooms, supervisor_evidence):
    supervisor_ids = set(supervisor_evidence)

    if not classrooms:
        return None, "no Intern Classroom membership exists"

    if len(supervisor_ids) > 1:
        return None, (
            "conflicting legacy supervisor evidence: "
            + ", ".join(str(value) for value in sorted(supervisor_ids))
        )

    if len(supervisor_ids) == 1:
        supervisor_id = next(iter(supervisor_ids))
        matches = [
            classroom
            for classroom in classrooms
            if classroom["supervisor_id"] == supervisor_id
        ]
        if len(matches) == 1:
            sources = ", ".join(sorted(supervisor_evidence[supervisor_id]))
            return matches[0], f"unique supervisor match via {sources}"
        if not matches:
            return None, (
                f"legacy supervisor {supervisor_id} does not match any "
                "current Intern Classroom membership"
            )
        return None, (
            f"legacy supervisor {supervisor_id} matches multiple Intern Classrooms"
        )

    if len(classrooms) == 1:
        return classrooms[0], "only Intern Classroom membership"

    return None, f"{len(classrooms)} Intern Classroom memberships and no unique supervisor evidence"


def _validate_manual_target(conn, student_id: int, classroom_id: int):
    row = conn.execute(
        """
        SELECT
            c.id,
            c.supervisor_id,
            c.name,
            c.section,
            COALESCE(c.archived, 0) AS archived,
            cs.joined_at
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        WHERE cs.student_id = ?
          AND c.id = ?
          AND COALESCE(c.classroom_type, 'classroom') = 'internship'
        LIMIT 1
        """,
        (student_id, classroom_id),
    ).fetchone()
    if not row:
        return None
    return {
        "id": int(_row_value(row, "id", 0, 0)),
        "supervisor_id": int(_row_value(row, "supervisor_id", 1, 0)),
        "name": str(_row_value(row, "name", 2, "Intern Classroom") or "Intern Classroom"),
        "section": str(_row_value(row, "section", 3, "") or ""),
        "archived": bool(_row_value(row, "archived", 4, 0)),
        "joined_at": _row_value(row, "joined_at", 5, None),
    }


def _build_plan(conn, rows, manual_classroom_id: int | None):
    by_student = defaultdict(list)
    for row in rows:
        by_student[int(_row_value(row, "student_id", 1, 0))].append(row)

    planned = []
    skipped = []

    for student_id, attendance_rows in sorted(by_student.items()):
        first = attendance_rows[0]
        username = str(_row_value(first, "username", 7, "") or "")
        email = str(_row_value(first, "email", 8, "") or "")
        classrooms = _intern_classrooms(conn, student_id)
        evidence = _legacy_supervisor_evidence(conn, student_id)

        if manual_classroom_id is not None:
            target = _validate_manual_target(conn, student_id, manual_classroom_id)
            if target is None:
                skipped.append(
                    {
                        "student_id": student_id,
                        "username": username,
                        "email": email,
                        "rows": attendance_rows,
                        "classrooms": classrooms,
                        "reason": (
                            f"classroom {manual_classroom_id} is not an Intern Classroom "
                            "membership for this student"
                        ),
                    }
                )
                continue
            basis = "explicit --classroom-id after membership validation"
        else:
            target, basis = _infer_target(classrooms, evidence)
            if target is None:
                skipped.append(
                    {
                        "student_id": student_id,
                        "username": username,
                        "email": email,
                        "rows": attendance_rows,
                        "classrooms": classrooms,
                        "reason": basis,
                    }
                )
                continue

        planned.append(
            {
                "student_id": student_id,
                "username": username,
                "email": email,
                "rows": attendance_rows,
                "target": target,
                "basis": basis,
                "supervisor_evidence": evidence,
            }
        )

    return planned, skipped


def _classroom_label(classroom) -> str:
    if not classroom:
        return "—"
    section = f" · {classroom['section']}" if classroom.get("section") else ""
    archive = " [archived]" if classroom.get("archived") else ""
    return (
        f"#{classroom['id']} {classroom['name']}{section}"
        f" · supervisor={classroom['supervisor_id']}{archive}"
    )


def _print_preview(planned, skipped) -> None:
    print("\nNexora legacy OJT attendance repair preview")
    print("=" * 48)
    print(f"Database engine: {'PostgreSQL' if using_postgres() else 'SQLite'}")
    if not using_postgres():
        print(f"SQLite path: {db_module.SQLITE_PATH}")

    planned_sessions = sum(len(item["rows"]) for item in planned)
    planned_logs = sum(
        int(_row_value(row, "log_count", 6, 0) or 0)
        for item in planned
        for row in item["rows"]
    )
    skipped_sessions = sum(len(item["rows"]) for item in skipped)

    print(f"Safe student mappings: {len(planned)}")
    print(f"Legacy attendance sessions ready to map: {planned_sessions}")
    print(f"Logs attached to those sessions: {planned_logs}")
    print(f"Skipped/ambiguous legacy sessions: {skipped_sessions}")

    if planned:
        print("\nSafe mappings:")
        for item in planned:
            rows = item["rows"]
            log_count = sum(int(_row_value(row, "log_count", 6, 0) or 0) for row in rows)
            identity = item["username"] or item["email"] or f"user-{item['student_id']}"
            print(
                f"  user={item['student_id']} ({identity}) "
                f"sessions={len(rows)} logs={log_count}"
            )
            print(f"    -> {_classroom_label(item['target'])}")
            print(f"    basis: {item['basis']}")
            attendance_ids = ", ".join(str(int(_row_value(row, "id", 0, 0))) for row in rows)
            print(f"    attendance ids: {attendance_ids}")

    if skipped:
        print("\nSkipped mappings:")
        for item in skipped:
            identity = item["username"] or item["email"] or f"user-{item['student_id']}"
            print(
                f"  user={item['student_id']} ({identity}) "
                f"sessions={len(item['rows'])}: {item['reason']}"
            )
            if item["classrooms"]:
                for classroom in item["classrooms"]:
                    print(f"    candidate {_classroom_label(classroom)}")
            else:
                print("    candidate classrooms: none")

    print("\nNo data has been changed yet.")


def _apply_plan(conn, planned) -> int:
    updated = 0
    for item in planned:
        attendance_ids = [
            int(_row_value(row, "id", 0, 0))
            for row in item["rows"]
        ]
        if not attendance_ids:
            continue

        placeholders = ",".join("?" for _ in attendance_ids)
        cursor = conn.execute(
            f"""
            UPDATE attendance
            SET classroom_id = ?
            WHERE student_id = ?
              AND classroom_id IS NULL
              AND id IN ({placeholders})
            """,
            tuple(
                [
                    int(item["target"]["id"]),
                    int(item["student_id"]),
                ]
                + attendance_ids
            ),
        )
        changed = int(getattr(cursor, "rowcount", 0) or 0)
        if changed != len(attendance_ids):
            raise RuntimeError(
                f"Expected to update {len(attendance_ids)} attendance rows for "
                f"user {item['student_id']}, but updated {changed}."
            )

        remaining = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM attendance
            WHERE student_id = ?
              AND classroom_id IS NULL
              AND id IN ({placeholders})
            """,
            tuple([int(item["student_id"])] + attendance_ids),
        ).fetchone()
        if int(remaining[0] or 0):
            raise RuntimeError(
                f"Verification failed for user {item['student_id']}; "
                "one or more attendance rows are still unscoped."
            )
        updated += changed

    return updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or repair legacy attendance rows whose classroom_id is NULL "
            "by assigning only safe Intern Classroom mappings."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the previewed safe mappings. Without this flag the script is read-only.",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        help="Limit preview/repair to one student users.id value.",
    )
    parser.add_argument(
        "--classroom-id",
        type=int,
        help=(
            "Explicit Intern Classroom target. Requires --user-id and is accepted "
            "only when that student is a member of the classroom."
        ),
    )
    args = parser.parse_args()

    if args.classroom_id is not None and args.user_id is None:
        parser.error("--classroom-id requires --user-id")

    conn = get_db_connection()
    try:
        _require_current_schema(conn)
        rows = _legacy_attendance(conn, args.user_id)

        if not rows:
            print("No legacy attendance rows with classroom_id IS NULL were found.")
            conn.rollback()
            return 0

        planned, skipped = _build_plan(conn, rows, args.classroom_id)
        _print_preview(planned, skipped)

        if not args.apply:
            if planned:
                print("\nRun again with --apply only after reviewing the mappings above.")
            elif skipped and args.user_id is not None:
                print(
                    "\nNothing can be repaired automatically for this student. "
                    "After verifying the correct classroom, rerun with "
                    "--user-id <id> --classroom-id <id> to preview an explicit mapping."
                )
            conn.rollback()
            return 0

        if not planned:
            conn.rollback()
            print("\nNo safe mappings were available. Nothing was changed.")
            return 0

        updated = _apply_plan(conn, planned)
        conn.commit()
        print(
            f"\nRepair complete. {updated} legacy attendance session"
            f"{'s' if updated != 1 else ''} assigned to Intern Classroom scope."
        )
        print(
            "Existing logs were not rewritten; they now inherit the repaired "
            "classroom/supervisor scope through attendance_id."
        )
        if skipped:
            skipped_count = sum(len(item["rows"]) for item in skipped)
            print(
                f"{skipped_count} ambiguous session"
                f"{'s were' if skipped_count != 1 else ' was'} left unchanged."
            )
        return 0
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"Repair failed and was rolled back: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
