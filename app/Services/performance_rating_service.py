"""Daily OJT performance rating conversion and persistence helpers.

The supervisor's original star value remains the source input. Percentages are
calculated deterministically from the approved rating anchors so controllers,
bulk actions, profiles, reports, and insights can all share one rule.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.Models.db import get_db_connection, using_postgres


MIN_STAR_RATING = Decimal("1.0")
MAX_STAR_RATING = Decimal("5.0")
STAR_RATING_STEP = Decimal("0.1")
PERCENTAGE_PRECISION = Decimal("0.1")
MAX_DAILY_RATING_COMMENT_LENGTH = 2000

# Approved anchors for the Nexora daily OJT performance scale.
# Values between anchors are linearly interpolated.
RATING_ANCHORS = (
    (Decimal("1.0"), Decimal("60.0")),
    (Decimal("2.0"), Decimal("70.0")),
    (Decimal("3.0"), Decimal("80.0")),
    (Decimal("4.0"), Decimal("90.0")),
    (Decimal("4.7"), Decimal("96.0")),
    (Decimal("5.0"), Decimal("100.0")),
)


def normalize_star_rating(value):
    """Validate and normalize a supervisor-selected 1.0-5.0 star rating."""
    try:
        rating = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, TypeError, ValueError):
        raise ValueError("Star rating must be a number from 1.0 to 5.0.")

    if not rating.is_finite():
        raise ValueError("Star rating must be a finite number from 1.0 to 5.0.")
    if rating < MIN_STAR_RATING or rating > MAX_STAR_RATING:
        raise ValueError("Star rating must be between 1.0 and 5.0.")

    normalized = rating.quantize(STAR_RATING_STEP, rounding=ROUND_HALF_UP)
    if rating != normalized:
        raise ValueError("Star rating must use 0.1-star increments.")
    return normalized


def star_rating_to_percentage(value):
    """Convert a validated star rating to its deterministic percentage."""
    rating = normalize_star_rating(value)

    for anchor_star, anchor_percentage in RATING_ANCHORS:
        if rating == anchor_star:
            return anchor_percentage.quantize(PERCENTAGE_PRECISION)

    for index in range(len(RATING_ANCHORS) - 1):
        lower_star, lower_percentage = RATING_ANCHORS[index]
        upper_star, upper_percentage = RATING_ANCHORS[index + 1]
        if lower_star < rating < upper_star:
            distance = upper_star - lower_star
            progress = (rating - lower_star) / distance
            percentage = lower_percentage + (
                progress * (upper_percentage - lower_percentage)
            )
            return percentage.quantize(
                PERCENTAGE_PRECISION,
                rounding=ROUND_HALF_UP,
            )

    raise ValueError("Star rating could not be converted.")


def build_daily_rating_snapshot(value):
    """Return storage-ready star and percentage values without inventing a grade."""
    rating = normalize_star_rating(value)
    percentage = star_rating_to_percentage(rating)
    return {
        "star_rating": float(rating),
        "percentage": float(percentage),
    }


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


def ensure_daily_performance_rating_schema():
    """Create the additive one-rating-per-attendance-day table."""
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_performance_ratings (
                    attendance_id INTEGER PRIMARY KEY REFERENCES attendance(id) ON DELETE CASCADE,
                    supervisor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    star_rating NUMERIC(2,1) NOT NULL,
                    percentage NUMERIC(5,1) NOT NULL,
                    comment TEXT,
                    rated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_performance_ratings (
                    attendance_id INTEGER PRIMARY KEY REFERENCES attendance(id) ON DELETE CASCADE,
                    supervisor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    star_rating REAL NOT NULL,
                    percentage REAL NOT NULL,
                    comment TEXT,
                    rated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_performance_ratings_supervisor ON daily_performance_ratings(supervisor_id)"
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


def _rating_dict(row):
    if not row:
        return None
    return {
        "attendance_id": int(_row_value(row, "attendance_id", 0, 0)),
        "supervisor_id": int(_row_value(row, "supervisor_id", 1, 0)),
        "star_rating": float(_row_value(row, "star_rating", 2, 0) or 0),
        "percentage": float(_row_value(row, "percentage", 3, 0) or 0),
        "comment": _row_value(row, "comment", 4, "") or "",
        "rated_at": _row_value(row, "rated_at", 5, None),
        "updated_at": _row_value(row, "updated_at", 6, None),
    }


def get_daily_performance_rating_for_supervisor(supervisor_id, classroom_id, attendance_id):
    """Return one rating only when the supervisor owns that attendance classroom."""
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
        attendance_id = int(attendance_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        allowed = conn.execute(
            """
            SELECT 1
            FROM attendance a
            JOIN classrooms c ON c.id = a.classroom_id
            WHERE a.id = ?
              AND a.classroom_id = ?
              AND c.supervisor_id = ?
            LIMIT 1
            """,
            (attendance_id, classroom_id, supervisor_id),
        ).fetchone()
        if not allowed:
            return None
        row = conn.execute(
            """
            SELECT attendance_id, supervisor_id, star_rating, percentage, comment, rated_at, updated_at
            FROM daily_performance_ratings
            WHERE attendance_id = ?
            LIMIT 1
            """,
            (attendance_id,),
        ).fetchone()
        return _rating_dict(row)
    finally:
        conn.close()


def get_daily_performance_rating_for_student(student_id, attendance_id):
    """Return one rating only for the student who owns the attendance day."""
    try:
        student_id = int(student_id)
        attendance_id = int(attendance_id)
    except (TypeError, ValueError):
        return None

    conn = get_db_connection()
    try:
        allowed = conn.execute(
            "SELECT 1 FROM attendance WHERE id = ? AND student_id = ? LIMIT 1",
            (attendance_id, student_id),
        ).fetchone()
        if not allowed:
            return None
        row = conn.execute(
            """
            SELECT attendance_id, supervisor_id, star_rating, percentage, comment, rated_at, updated_at
            FROM daily_performance_ratings
            WHERE attendance_id = ?
            LIMIT 1
            """,
            (attendance_id,),
        ).fetchone()
        return _rating_dict(row)
    finally:
        conn.close()


def save_daily_performance_rating(
    supervisor_id,
    classroom_id,
    attendance_id,
    star_rating,
    comment="",
):
    """Create or update one supervisor-entered rating for a completed OJT day."""
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
        attendance_id = int(attendance_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid attendance day."}

    try:
        snapshot = build_daily_rating_snapshot(star_rating)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    comment = (comment or "").strip()
    if len(comment) > MAX_DAILY_RATING_COMMENT_LENGTH:
        return {
            "ok": False,
            "error": f"Daily performance comment must be {MAX_DAILY_RATING_COMMENT_LENGTH:,} characters or fewer.",
        }

    conn = get_db_connection()
    try:
        attendance = conn.execute(
            """
            SELECT a.student_id, a.status
            FROM attendance a
            JOIN classrooms c ON c.id = a.classroom_id
            WHERE a.id = ?
              AND a.classroom_id = ?
              AND c.supervisor_id = ?
            LIMIT 1
            """,
            (attendance_id, classroom_id, supervisor_id),
        ).fetchone()
        if not attendance:
            return {"ok": False, "error": "Attendance day not found in this Intern Classroom."}
        if _row_value(attendance, "status", 1, "Open") == "Open":
            return {"ok": False, "error": "Clock-out must be completed before daily performance can be rated."}

        now = datetime.now()
        conn.execute(
            """
            INSERT INTO daily_performance_ratings (
                attendance_id,
                supervisor_id,
                star_rating,
                percentage,
                comment,
                rated_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (attendance_id) DO UPDATE SET
                supervisor_id = excluded.supervisor_id,
                star_rating = excluded.star_rating,
                percentage = excluded.percentage,
                comment = excluded.comment,
                updated_at = excluded.updated_at
            """,
            (
                attendance_id,
                supervisor_id,
                snapshot["star_rating"],
                snapshot["percentage"],
                comment or None,
                now,
                now,
            ),
        )
        conn.commit()
        return {
            "ok": True,
            "error": None,
            "attendance_id": attendance_id,
            "classroom_id": classroom_id,
            "student_id": int(_row_value(attendance, "student_id", 0, 0)),
            "star_rating": snapshot["star_rating"],
            "percentage": snapshot["percentage"],
            "comment": comment,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
