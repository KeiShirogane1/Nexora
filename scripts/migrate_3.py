"""
scripts/migrate_phase3.py
Phase 3 idempotent migration for internship/assignment consolidation.

- Adds internships.supervisor_id if missing
- Backfills supervisor_id from supervisor_email/username where safely matched
- Backfills student_assignments from internships
- Creates required indexes
- Transactional, rollback on failure, repeatable
"""
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.Models.db import get_db_connection, using_postgres

def _ensure_column(cursor, table, column, definition):
    """Ensure column exists (SQLite via PRAGMA, Postgres via information_schema)."""
    if using_postgres():
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
            (table, column),
        )
        exists = cursor.fetchone() is not None
        if not exists:
            # definition like "INTEGER REFERENCES users(id)"
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            print(f"Added {table}.{column}")
    else:
        cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            print(f"Added {table}.{column}")

def migrate():
    print("Starting Phase 3 migration...")
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Ensure supervisor_id column
        print("Ensuring internships.supervisor_id...")
        _ensure_column(cursor, "internships", "supervisor_id", "INTEGER REFERENCES users(id)")

        # 2. Ensure indexes
        indexes = [
            ("idx_student_assignments_student_id", "student_assignments(student_id)"),
            ("idx_student_assignments_supervisor_id", "student_assignments(supervisor_id)"),
            ("idx_tasks_student_id", "tasks(student_id)"),
            ("idx_tasks_supervisor_id", "tasks(supervisor_id)"),
            ("idx_internships_student_id", "internships(student_id)"),
            ("idx_internships_supervisor_id", "internships(supervisor_id)"),
            ("idx_feedback_student_id", "feedback(student_id)"),
            ("idx_feedback_supervisor_id", "feedback(supervisor_id)"),
        ]
        for idx_name, target in indexes:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {target}")
        print(f"Ensured {len(indexes)} indexes")

        # 3. Backfill supervisor_id from supervisor_email or supervisor_name
        # Count before
        cursor.execute("SELECT COUNT(*) FROM internships")
        total_internships = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM internships WHERE supervisor_id IS NOT NULL")
        before_filled = cursor.fetchone()[0]
        print(f"Internships total {total_internships}, already with supervisor_id {before_filled}")

        # Fetch internships needing backfill
        cursor.execute(
            "SELECT id, student_id, supervisor_email, supervisor_name, supervisor_id FROM internships WHERE supervisor_id IS NULL"
        )
        to_fill = cursor.fetchall()
        print(f"Internships needing supervisor_id backfill: {len(to_fill)}")

        backfilled = 0
        ambiguous = 0
        for row in to_fill:
            # row may be tuple or HybridRow
            if hasattr(row, "_mapping"):
                rid = row["id"]
                email = row["supervisor_email"]
                name = row["supervisor_name"]
            else:
                rid = row[0]
                email = row[2]
                name = row[3]

            supervisor_id = None
            # Prefer email match (exact, lower)
            if email:
                cursor.execute(
                    "SELECT id FROM users WHERE LOWER(email) = LOWER(?) AND role = 'supervisor' LIMIT 1",
                    (email.strip(),),
                )
                r = cursor.fetchone()
                if r:
                    supervisor_id = r[0] if isinstance(r, tuple) else r["id"]

            # Fallback to username match if email not found and name looks like username
            if not supervisor_id and name:
                # Only if name is single token without spaces (likely username)
                if " " not in name.strip():
                    cursor.execute(
                        "SELECT id FROM users WHERE username = ? AND role = 'supervisor' LIMIT 1",
                        (name.strip(),),
                    )
                    r = cursor.fetchone()
                    if r:
                        supervisor_id = r[0] if isinstance(r, tuple) else r["id"]

            if supervisor_id:
                # Do not overwrite if already set (we are in IS NULL set, so safe)
                cursor.execute(
                    "UPDATE internships SET supervisor_id = ? WHERE id = ? AND supervisor_id IS NULL",
                    (supervisor_id, rid),
                )
                if cursor.rowcount:
                    backfilled += 1
            else:
                # Cannot safely match — leave unchanged
                ambiguous += 1
                if email or name:
                    print(f"  Ambiguous internship {rid}: email={email!r} name={name!r} -> no supervisor match, left NULL")

        print(f"Backfilled internships.supervisor_id: {backfilled}, ambiguous left NULL: {ambiguous}")

        # 4. Backfill student_assignments from internships
        cursor.execute("SELECT COUNT(*) FROM student_assignments")
        before_assign = cursor.fetchone()[0]
        print(f"student_assignments before: {before_assign}")

        # For each internship with supervisor_id now set, ensure assignment exists
        cursor.execute("SELECT student_id, supervisor_id FROM internships WHERE supervisor_id IS NOT NULL")
        internships_with_sup = cursor.fetchall()
        inserted_assignments = 0
        for row in internships_with_sup:
            if hasattr(row, "_mapping"):
                sid = row["student_id"]
                sup = row["supervisor_id"]
            else:
                sid = row[0]
                sup = row[1]
            # Use ON CONFLICT / OR IGNORE handling
            if using_postgres():
                cursor.execute(
                    "INSERT INTO student_assignments (student_id, supervisor_id) VALUES (?, ?) ON CONFLICT (student_id, supervisor_id) DO NOTHING",
                    (sid, sup),
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO student_assignments (student_id, supervisor_id) VALUES (?, ?)",
                    (sid, sup),
                )
            if cursor.rowcount:
                inserted_assignments += 1

        print(f"Inserted student_assignments from internships: {inserted_assignments}")

        cursor.execute("SELECT COUNT(*) FROM student_assignments")
        after_assign = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM internships WHERE supervisor_id IS NOT NULL")
        after_filled = cursor.fetchone()[0]

        print(f"After: internships with supervisor_id {after_filled}, student_assignments {after_assign}")

        # 5. Verify — no duplicate active internship per student? Application-level check, not DB constraint here
        # For data safety, just report if any student has multiple Active internships
        cursor.execute("SELECT student_id, COUNT(*) c FROM internships WHERE status='Active' GROUP BY student_id HAVING c > 1")
        dup_active = cursor.fetchall()
        if dup_active:
            print(f"WARNING: students with multiple Active internships: {len(dup_active)}")
            for r in dup_active:
                print(f"  student {r[0]} count {r[1]}")
        else:
            print("No duplicate Active internships found")

        # Commit only after validation
        conn.commit()
        print("Phase 3 migration committed successfully")
        print(f"Summary: backfilled {backfilled} internships, inserted {inserted_assignments} assignments, ambiguous {ambiguous}")

    except Exception as e:
        conn.rollback()
        print(f"Phase 3 migration FAILED, rolled back: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    migrate()
