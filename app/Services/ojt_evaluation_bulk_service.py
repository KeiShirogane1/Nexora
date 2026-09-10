"""Atomic multi-intern Official OJT Evaluation persistence.

Bulk evaluation reuses the existing manual rubric validation rules and stores one
separate official evaluation per selected intern. Submitted evaluations are never
overwritten by a bulk action.
"""
from datetime import datetime

from app.Models.db import get_db_connection
from app.Services.ojt_evaluation_service import (
    MAX_REMARKS_LENGTH,
    _decimal,
    _normalize_items,
    _value,
)


def save_supervisor_ojt_evaluations_bulk(
    supervisor_id,
    classroom_id,
    student_ids,
    status,
    items,
    overall_score=None,
    remarks="",
):
    """Validate the full selection, then save every evaluation in one transaction."""
    try:
        supervisor_id = int(supervisor_id)
        classroom_id = int(classroom_id)
        normalized_student_ids = []
        seen = set()
        for raw_student_id in student_ids or []:
            student_id = int(raw_student_id)
            if student_id > 0 and student_id not in seen:
                normalized_student_ids.append(student_id)
                seen.add(student_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid intern or Intern Classroom."}

    if len(normalized_student_ids) < 2:
        return {"ok": False, "error": "Select at least two interns for bulk evaluation."}

    status = str(status or "").strip().lower()
    if status not in {"draft", "submitted"}:
        return {"ok": False, "error": "Invalid evaluation status."}

    remarks = str(remarks or "").strip()
    if len(remarks) > MAX_REMARKS_LENGTH:
        return {
            "ok": False,
            "error": f"Overall remarks must be {MAX_REMARKS_LENGTH:,} characters or fewer.",
        }

    try:
        normalized_overall = _decimal(
            overall_score,
            "Overall score",
            required=False,
            nonnegative=True,
        )
        normalized_items = _normalize_items(items, status)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    placeholders = ", ".join("?" for _ in normalized_student_ids)
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            "SELECT id FROM classrooms WHERE id = ? AND supervisor_id = ? LIMIT 1",
            (classroom_id, supervisor_id),
        ).fetchone()
        if not classroom:
            return {"ok": False, "error": "Intern Classroom was not found."}

        enrolled_rows = conn.execute(
            f"""
            SELECT student_id
            FROM classroom_students
            WHERE classroom_id = ? AND student_id IN ({placeholders})
            """,
            (classroom_id, *normalized_student_ids),
        ).fetchall()
        enrolled_ids = {
            int(_value(row, "student_id", 0, 0) or 0)
            for row in enrolled_rows
        }
        if enrolled_ids != set(normalized_student_ids):
            return {
                "ok": False,
                "error": "Every selected intern must be enrolled in this Intern Classroom.",
            }

        existing_rows = conn.execute(
            f"""
            SELECT id, student_id, status
            FROM ojt_evaluations
            WHERE classroom_id = ? AND student_id IN ({placeholders})
            """,
            (classroom_id, *normalized_student_ids),
        ).fetchall()
        existing_by_student = {
            int(_value(row, "student_id", 1, 0) or 0): row
            for row in existing_rows
        }
        submitted_ids = [
            student_id
            for student_id, row in existing_by_student.items()
            if str(_value(row, "status", 2, "draft") or "draft").strip().lower()
            == "submitted"
        ]
        if submitted_ids:
            return {
                "ok": False,
                "error": "Submitted evaluations cannot be overwritten. Reopen them as drafts first.",
            }

        now = datetime.now()
        submitted_at = now if status == "submitted" else None
        saved_ids = []

        for student_id in normalized_student_ids:
            existing = existing_by_student.get(student_id)
            if existing:
                evaluation_id = int(_value(existing, "id", 0, 0) or 0)
                conn.execute(
                    """
                    UPDATE ojt_evaluations
                    SET supervisor_id = ?, status = ?, overall_score = ?, remarks = ?,
                        updated_at = ?, submitted_at = ?
                    WHERE id = ? AND classroom_id = ? AND student_id = ?
                    """,
                    (
                        supervisor_id,
                        status,
                        float(normalized_overall) if normalized_overall is not None else None,
                        remarks or None,
                        now,
                        submitted_at,
                        evaluation_id,
                        classroom_id,
                        student_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO ojt_evaluations (
                        classroom_id, student_id, supervisor_id, status,
                        overall_score, remarks, created_at, updated_at, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        classroom_id,
                        student_id,
                        supervisor_id,
                        status,
                        float(normalized_overall) if normalized_overall is not None else None,
                        remarks or None,
                        now,
                        now,
                        submitted_at,
                    ),
                )
                row = conn.execute(
                    """
                    SELECT id
                    FROM ojt_evaluations
                    WHERE classroom_id = ? AND student_id = ?
                    LIMIT 1
                    """,
                    (classroom_id, student_id),
                ).fetchone()
                evaluation_id = int(_value(row, "id", 0, 0) or 0)

            conn.execute(
                "DELETE FROM ojt_evaluation_items WHERE evaluation_id = ?",
                (evaluation_id,),
            )
            for item in normalized_items:
                conn.execute(
                    """
                    INSERT INTO ojt_evaluation_items (
                        evaluation_id, criterion_name, rating_value, max_value,
                        weight, comments, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evaluation_id,
                        item["criterion_name"],
                        item["rating_value"],
                        item["max_value"],
                        item["weight"],
                        item["comments"] or None,
                        item["sort_order"],
                    ),
                )
            saved_ids.append(evaluation_id)

        conn.commit()
        return {
            "ok": True,
            "error": None,
            "classroom_id": classroom_id,
            "student_ids": normalized_student_ids,
            "evaluation_ids": saved_ids,
            "saved_count": len(saved_ids),
            "status": status,
            "item_count": len(normalized_items),
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
