"""Structured Daily OJT Logbook helpers."""
from datetime import datetime

from app.Models.db import get_db_connection, using_postgres
from app.Services.internship_schedule_service import attendance_local_datetime


MAX_LOG_TEXT_LENGTH = 5000
MAX_RELATED_WORK_ITEMS = 2


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


def _as_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _format_date(value):
    dt = _as_datetime(value)
    return dt.strftime("%b %d, %Y") if dt else "—"


def _format_time(value):
    dt = _as_datetime(value)
    return dt.strftime("%I:%M %p").lstrip("0") if dt else None


def ensure_logbook_schema():
    """Extend legacy logs and create additive Daily Logbook-to-Work links."""
    conn = get_db_connection()
    try:
        if using_postgres():
            statements = [
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS entry_type TEXT NOT NULL DEFAULT 'activity'",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS accomplishment TEXT",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS reflection TEXT",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS challenges TEXT",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS related_assignment_id INTEGER REFERENCES classroom_assignments(id) ON DELETE SET NULL",
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
            ]
            for statement in statements:
                conn.execute(statement)
        else:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(logs)").fetchall()]
            additions = (
                ("entry_type", "ALTER TABLE logs ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'activity'"),
                ("accomplishment", "ALTER TABLE logs ADD COLUMN accomplishment TEXT"),
                ("reflection", "ALTER TABLE logs ADD COLUMN reflection TEXT"),
                ("challenges", "ALTER TABLE logs ADD COLUMN challenges TEXT"),
                (
                    "related_assignment_id",
                    "ALTER TABLE logs ADD COLUMN related_assignment_id INTEGER REFERENCES classroom_assignments(id) ON DELETE SET NULL",
                ),
                ("updated_at", "ALTER TABLE logs ADD COLUMN updated_at TIMESTAMP"),
            )
            for name, statement in additions:
                if name not in columns:
                    conn.execute(statement)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_log_work_links (
                log_id INTEGER NOT NULL REFERENCES logs(id) ON DELETE CASCADE,
                assignment_id INTEGER NOT NULL REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (log_id, assignment_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_log_work_assignment ON daily_log_work_links(assignment_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_log_work_log ON daily_log_work_links(log_id, sort_order)"
        )

        # Preserve every existing single Work link. The legacy column stays in
        # place as the compatibility first-link for older services while the
        # additive table becomes authoritative for multi-Work Daily entries.
        if using_postgres():
            conn.execute(
                """
                INSERT INTO daily_log_work_links (log_id, assignment_id, sort_order)
                SELECT id, related_assignment_id, 0
                FROM logs
                WHERE entry_type = 'daily'
                  AND related_assignment_id IS NOT NULL
                ON CONFLICT (log_id, assignment_id) DO NOTHING
                """
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_log_work_links (log_id, assignment_id, sort_order)
                SELECT id, related_assignment_id, 0
                FROM logs
                WHERE entry_type = 'daily'
                  AND related_assignment_id IS NOT NULL
                """
            )

        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_logs_student_daily
               ON logs(student_id, entry_type, created_at)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_logs_related_assignment
               ON logs(related_assignment_id)"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_logs_daily_attendance_unique
               ON logs(attendance_id)
               WHERE entry_type = 'daily'"""
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _normalize_assignment_ids(related_assignment_ids=None, related_assignment_id=None):
    """Normalize a Daily entry's Work selection while retaining single-link callers."""
    if related_assignment_ids is None:
        raw_values = []
    elif isinstance(related_assignment_ids, (str, int)):
        raw_values = [related_assignment_ids]
    else:
        raw_values = list(related_assignment_ids)

    if not raw_values and related_assignment_id not in (None, ""):
        raw_values.append(related_assignment_id)

    normalized = []
    for raw_value in raw_values:
        if raw_value in (None, ""):
            continue
        try:
            assignment_id = int(raw_value)
        except (TypeError, ValueError):
            return [], "Choose valid related Work items."
        if assignment_id not in normalized:
            normalized.append(assignment_id)

    if len(normalized) > MAX_RELATED_WORK_ITEMS:
        return [], f"Choose up to {MAX_RELATED_WORK_ITEMS} related Work items for one Daily OJT entry."
    return normalized, None


def get_logbook_work_items(log_id, conn=None):
    """Return every Work item linked to one Daily OJT log, in saved order."""
    try:
        log_id = int(log_id)
    except (TypeError, ValueError):
        return []

    owns_connection = conn is None
    if owns_connection:
        conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                link.assignment_id,
                a.title,
                a.due_at,
                a.created_at,
                link.sort_order
            FROM daily_log_work_links link
            JOIN classroom_assignments a ON a.id = link.assignment_id
            WHERE link.log_id = ?
            ORDER BY link.sort_order ASC, link.assignment_id ASC
            """,
            (log_id,),
        ).fetchall()

        if not rows:
            legacy = conn.execute(
                """
                SELECT a.id AS assignment_id, a.title, a.due_at, a.created_at, 0 AS sort_order
                FROM logs l
                JOIN classroom_assignments a ON a.id = l.related_assignment_id
                WHERE l.id = ? AND l.related_assignment_id IS NOT NULL
                LIMIT 1
                """,
                (log_id,),
            ).fetchall()
            rows = legacy

        items = []
        for row in rows:
            due_at = _row_value(row, "due_at", 2, None)
            created_at = _row_value(row, "created_at", 3, None)
            items.append(
                {
                    "id": int(_row_value(row, "assignment_id", 0, 0)),
                    "title": _row_value(row, "title", 1, "Work") or "Work",
                    "due_at": due_at,
                    "created_at": created_at,
                    "date_label": (
                        f"Due {_format_date(due_at)}"
                        if due_at
                        else f"Assigned {_format_date(created_at)}"
                    ),
                }
            )
        return items
    finally:
        if owns_connection:
            conn.close()


def _attach_work_items(conn, entry):
    items = get_logbook_work_items(entry.get("id"), conn=conn)
    entry["related_work_items"] = items
    entry["related_assignment_ids"] = [item["id"] for item in items]
    entry["related_work_titles"] = [item["title"] for item in items]
    if items:
        entry["related_assignment_id"] = items[0]["id"]
        entry["related_work_title"] = " · ".join(item["title"] for item in items)
    else:
        entry["related_assignment_id"] = None
        entry["related_work_title"] = None
    return entry


def _visible_work(conn, student_id, classroom_id, current_log_id=None):
    """Return assigned Work that has not already been completed in another OJT day."""
    if not classroom_id:
        return []

    current_log_id = int(current_log_id or 0)
    rows = conn.execute(
        """
        SELECT a.id, a.title, a.due_at, a.created_at
        FROM classroom_assignments a
        WHERE a.classroom_id = ?
          AND (
                NOT EXISTS (
                    SELECT 1
                    FROM classroom_assignment_recipients r
                    WHERE r.assignment_id = a.id
                )
                OR EXISTS (
                    SELECT 1
                    FROM classroom_assignment_recipients r
                    WHERE r.assignment_id = a.id
                      AND r.student_id = ?
                )
          )
          AND (
                NOT EXISTS (
                    SELECT 1
                    FROM daily_log_work_links completed_link
                    JOIN logs completed_log ON completed_log.id = completed_link.log_id
                    JOIN attendance completed_attendance ON completed_attendance.id = completed_log.attendance_id
                    WHERE completed_link.assignment_id = a.id
                      AND completed_log.student_id = ?
                      AND completed_log.entry_type = 'daily'
                      AND completed_attendance.classroom_id = ?
                      AND completed_attendance.status = 'Completed'
                )
                OR EXISTS (
                    SELECT 1
                    FROM daily_log_work_links current_link
                    WHERE current_link.log_id = ?
                      AND current_link.assignment_id = a.id
                )
          )
        ORDER BY a.created_at DESC, a.id DESC
        """,
        (classroom_id, student_id, student_id, classroom_id, current_log_id),
    ).fetchall()

    work_options = []
    for row in rows:
        work_title = _row_value(row, "title", 1, "Work")
        due_at = _row_value(row, "due_at", 2, None)
        created_at = _row_value(row, "created_at", 3, None)
        date_label = (
            f"Due {_format_date(due_at)}"
            if due_at
            else f"Assigned {_format_date(created_at)}"
        )
        work_options.append(
            {
                "id": int(_row_value(row, "id", 0, 0)),
                "title": f"{date_label} — {work_title}",
                "work_title": work_title,
                "due_at": due_at,
                "created_at": created_at,
                "date_label": date_label,
            }
        )
    return work_options


def _can_reference_work(conn, student_id, classroom_id, assignment_id, current_log_id=None):
    if not classroom_id or not assignment_id:
        return False
    current_log_id = int(current_log_id or 0)
    row = conn.execute(
        """
        SELECT 1
        FROM classroom_assignments a
        WHERE a.id = ?
          AND a.classroom_id = ?
          AND (
                NOT EXISTS (
                    SELECT 1
                    FROM classroom_assignment_recipients r
                    WHERE r.assignment_id = a.id
                )
                OR EXISTS (
                    SELECT 1
                    FROM classroom_assignment_recipients r
                    WHERE r.assignment_id = a.id
                      AND r.student_id = ?
                )
          )
          AND (
                NOT EXISTS (
                    SELECT 1
                    FROM daily_log_work_links completed_link
                    JOIN logs completed_log ON completed_log.id = completed_link.log_id
                    JOIN attendance completed_attendance ON completed_attendance.id = completed_log.attendance_id
                    WHERE completed_link.assignment_id = a.id
                      AND completed_log.student_id = ?
                      AND completed_log.entry_type = 'daily'
                      AND completed_attendance.classroom_id = ?
                      AND completed_attendance.status = 'Completed'
                )
                OR EXISTS (
                    SELECT 1
                    FROM daily_log_work_links current_link
                    WHERE current_link.log_id = ?
                      AND current_link.assignment_id = a.id
                )
          )
        LIMIT 1
        """,
        (assignment_id, classroom_id, student_id, student_id, classroom_id, current_log_id),
    ).fetchone()
    return row is not None


def save_daily_log(
    student_id,
    attendance_id,
    accomplishment,
    reflection="",
    challenges="",
    related_assignment_id=None,
    related_assignment_ids=None,
):
    """Create/update one Daily OJT entry and link up to two assigned Work items."""
    try:
        student_id = int(student_id)
        attendance_id = int(attendance_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid attendance session.", "classroom_id": None}

    accomplishment = (accomplishment or "").strip()
    reflection = (reflection or "").strip()
    challenges = (challenges or "").strip()

    if not accomplishment:
        return {"ok": False, "error": "Daily accomplishment is required.", "classroom_id": None}
    if any(len(value) > MAX_LOG_TEXT_LENGTH for value in (accomplishment, reflection, challenges)):
        return {
            "ok": False,
            "error": f"Each Daily OJT text field must be {MAX_LOG_TEXT_LENGTH:,} characters or fewer.",
            "classroom_id": None,
        }

    normalized_assignment_ids, normalization_error = _normalize_assignment_ids(
        related_assignment_ids,
        related_assignment_id,
    )
    if normalization_error:
        return {"ok": False, "error": normalization_error, "classroom_id": None}

    conn = get_db_connection()
    try:
        attendance = conn.execute(
            """
            SELECT id, classroom_id, status
            FROM attendance
            WHERE id = ? AND student_id = ?
            LIMIT 1
            """,
            (attendance_id, student_id),
        ).fetchone()
        if not attendance:
            return {"ok": False, "error": "Attendance session not found.", "classroom_id": None}

        classroom_id = _row_value(attendance, "classroom_id", 1, None)
        status = _row_value(attendance, "status", 2, "")
        if status != "Open":
            return {
                "ok": False,
                "error": "Daily OJT entries can only be changed while the attendance session is open.",
                "classroom_id": classroom_id,
            }

        existing = conn.execute(
            """
            SELECT id
            FROM logs
            WHERE attendance_id = ?
              AND student_id = ?
              AND entry_type = 'daily'
            LIMIT 1
            """,
            (attendance_id, student_id),
        ).fetchone()
        current_log_id = int(_row_value(existing, "id", 0, 0)) if existing else 0

        for assignment_id in normalized_assignment_ids:
            if not _can_reference_work(
                conn,
                student_id,
                classroom_id,
                assignment_id,
                current_log_id=current_log_id,
            ):
                return {
                    "ok": False,
                    "error": "One of those Work items is not available to you or was already completed in an earlier OJT day.",
                    "classroom_id": classroom_id,
                }

        now = datetime.now()
        compatibility_assignment_id = normalized_assignment_ids[0] if normalized_assignment_ids else None

        if existing:
            log_id = current_log_id
            conn.execute(
                """
                UPDATE logs
                SET content = ?,
                    accomplishment = ?,
                    reflection = ?,
                    challenges = ?,
                    related_assignment_id = ?,
                    updated_at = ?
                WHERE id = ? AND student_id = ?
                """,
                (
                    accomplishment,
                    accomplishment,
                    reflection or None,
                    challenges or None,
                    compatibility_assignment_id,
                    now,
                    log_id,
                    student_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO logs (
                    attendance_id,
                    student_id,
                    content,
                    created_at,
                    entry_type,
                    accomplishment,
                    reflection,
                    challenges,
                    related_assignment_id,
                    updated_at
                ) VALUES (?, ?, ?, ?, 'daily', ?, ?, ?, ?, ?)
                """,
                (
                    attendance_id,
                    student_id,
                    accomplishment,
                    now,
                    accomplishment,
                    reflection or None,
                    challenges or None,
                    compatibility_assignment_id,
                    now,
                ),
            )
            created = conn.execute(
                """
                SELECT id
                FROM logs
                WHERE attendance_id = ?
                  AND student_id = ?
                  AND entry_type = 'daily'
                LIMIT 1
                """,
                (attendance_id, student_id),
            ).fetchone()
            log_id = int(_row_value(created, "id", 0, 0))

        conn.execute("DELETE FROM daily_log_work_links WHERE log_id = ?", (log_id,))
        for sort_order, assignment_id in enumerate(normalized_assignment_ids):
            conn.execute(
                """
                INSERT INTO daily_log_work_links (log_id, assignment_id, sort_order)
                VALUES (?, ?, ?)
                """,
                (log_id, assignment_id, sort_order),
            )

        conn.commit()
        return {
            "ok": True,
            "error": None,
            "classroom_id": classroom_id,
            "log_id": log_id,
            "related_assignment_ids": normalized_assignment_ids,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _attendance_day_map(conn, student_id, classroom_id):
    if classroom_id is None:
        rows = conn.execute(
            """
            SELECT id, clock_in
            FROM attendance
            WHERE student_id = ? AND classroom_id IS NULL
            ORDER BY clock_in ASC, id ASC
            """,
            (student_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, clock_in
            FROM attendance
            WHERE student_id = ? AND classroom_id = ?
            ORDER BY clock_in ASC, id ASC
            """,
            (student_id, classroom_id),
        ).fetchall()

    date_numbers = {}
    mapping = {}
    next_day = 1
    for row in rows:
        attendance_id = int(_row_value(row, "id", 0, 0))
        local_clock = attendance_local_datetime(_row_value(row, "clock_in", 1, None))
        date_key = local_clock.date() if local_clock is not None else ("attendance", attendance_id)
        if date_key not in date_numbers:
            date_numbers[date_key] = next_day
            next_day += 1
        mapping[attendance_id] = date_numbers[date_key]
    return mapping


def _serialize_daily_row(row, day_map):
    attendance_id = int(_row_value(row, "attendance_id", 1, 0))
    hours = _row_value(row, "hours_rendered", 11, None)
    try:
        hours = float(hours) if hours is not None else None
    except (TypeError, ValueError):
        hours = None
    clock_in = attendance_local_datetime(_row_value(row, "clock_in", 9, None))
    clock_out = attendance_local_datetime(_row_value(row, "clock_out", 10, None))
    return {
        "id": int(_row_value(row, "id", 0, 0)),
        "attendance_id": attendance_id,
        "day_number": day_map.get(attendance_id),
        "accomplishment": _row_value(row, "accomplishment", 2, "") or "",
        "reflection": _row_value(row, "reflection", 3, "") or "",
        "challenges": _row_value(row, "challenges", 4, "") or "",
        "related_assignment_id": _row_value(row, "related_assignment_id", 5, None),
        "related_work_title": _row_value(row, "related_work_title", 6, None),
        "created_at": _row_value(row, "created_at", 7, None),
        "updated_at": _row_value(row, "updated_at", 8, None),
        "date": _format_date(clock_in),
        "time_in": _format_time(clock_in),
        "time_out": _format_time(clock_out),
        "hours_rendered": hours,
        "status": _row_value(row, "status", 12, "Open"),
    }


def get_daily_logbook_context(student_id, classroom_id=None, attendance_id=None):
    """Return structured Daily OJT entries for one authorized intern/classroom scope."""
    empty = {
        "entries": [],
        "current_entry": None,
        "work_options": [],
        "pending_work_count": 0,
        "total_entries": 0,
        "attendance_day_numbers": {},
    }
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return empty

    normalized_classroom_id = None
    if classroom_id not in (None, ""):
        try:
            normalized_classroom_id = int(classroom_id)
        except (TypeError, ValueError):
            return empty

    normalized_attendance_id = None
    if attendance_id not in (None, ""):
        try:
            normalized_attendance_id = int(attendance_id)
        except (TypeError, ValueError):
            normalized_attendance_id = None

    conn = get_db_connection()
    try:
        if normalized_classroom_id is not None:
            membership = conn.execute(
                """
                SELECT 1
                FROM classroom_students cs
                JOIN classrooms c ON c.id = cs.classroom_id
                WHERE cs.student_id = ?
                  AND cs.classroom_id = ?
                  AND COALESCE(c.classroom_type, 'classroom') = 'internship'
                LIMIT 1
                """,
                (student_id, normalized_classroom_id),
            ).fetchone()
            if not membership:
                return empty

        day_map = _attendance_day_map(conn, student_id, normalized_classroom_id)
        if normalized_classroom_id is not None:
            rows = conn.execute(
                """
                SELECT
                    l.id,
                    l.attendance_id,
                    l.accomplishment,
                    l.reflection,
                    l.challenges,
                    l.related_assignment_id,
                    ca.title AS related_work_title,
                    l.created_at,
                    l.updated_at,
                    a.clock_in,
                    a.clock_out,
                    a.hours_rendered,
                    a.status
                FROM logs l
                JOIN attendance a ON a.id = l.attendance_id
                LEFT JOIN classroom_assignments ca ON ca.id = l.related_assignment_id
                WHERE l.student_id = ?
                  AND l.entry_type = 'daily'
                  AND a.classroom_id = ?
                ORDER BY a.clock_in DESC, l.id DESC
                """,
                (student_id, normalized_classroom_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    l.id,
                    l.attendance_id,
                    l.accomplishment,
                    l.reflection,
                    l.challenges,
                    l.related_assignment_id,
                    ca.title AS related_work_title,
                    l.created_at,
                    l.updated_at,
                    a.clock_in,
                    a.clock_out,
                    a.hours_rendered,
                    a.status
                FROM logs l
                JOIN attendance a ON a.id = l.attendance_id
                LEFT JOIN classroom_assignments ca ON ca.id = l.related_assignment_id
                WHERE l.student_id = ?
                  AND l.entry_type = 'daily'
                  AND a.classroom_id IS NULL
                ORDER BY a.clock_in DESC, l.id DESC
                """,
                (student_id,),
            ).fetchall()

        entries = []
        for row in rows:
            entries.append(_attach_work_items(conn, _serialize_daily_row(row, day_map)))

        current_entry = next(
            (entry for entry in entries if entry["attendance_id"] == normalized_attendance_id),
            None,
        )
        current_log_id = current_entry["id"] if current_entry else None
        work_options = _visible_work(
            conn,
            student_id,
            normalized_classroom_id,
            current_log_id=current_log_id,
        )
        return {
            "entries": entries,
            "current_entry": current_entry,
            "work_options": work_options,
            "pending_work_count": len(work_options),
            "total_entries": len(entries),
            "attendance_day_numbers": day_map,
        }
    finally:
        conn.close()


def get_session_daily_log(student_id, attendance_id):
    """Return one structured Daily OJT entry for a student-owned attendance session."""
    try:
        student_id = int(student_id)
        attendance_id = int(attendance_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        attendance = conn.execute(
            "SELECT classroom_id FROM attendance WHERE id = ? AND student_id = ?",
            (attendance_id, student_id),
        ).fetchone()
        if not attendance:
            return None
        classroom_id = _row_value(attendance, "classroom_id", 0, None)
        day_map = _attendance_day_map(conn, student_id, classroom_id)
        row = conn.execute(
            """
            SELECT
                l.id,
                l.attendance_id,
                l.accomplishment,
                l.reflection,
                l.challenges,
                l.related_assignment_id,
                ca.title AS related_work_title,
                l.created_at,
                l.updated_at,
                a.clock_in,
                a.clock_out,
                a.hours_rendered,
                a.status
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            LEFT JOIN classroom_assignments ca ON ca.id = l.related_assignment_id
            WHERE l.student_id = ?
              AND l.attendance_id = ?
              AND l.entry_type = 'daily'
            LIMIT 1
            """,
            (student_id, attendance_id),
        ).fetchone()
        if not row:
            return None
        return _attach_work_items(conn, _serialize_daily_row(row, day_map))
    finally:
        conn.close()
