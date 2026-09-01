from flask import Blueprint, abort, render_template, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection


classwork_gradebook = Blueprint("classwork_gradebook", __name__)


def _value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            return row[key]
    except AttributeError:
        pass
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return default


@classwork_gradebook.route("/supervisor/classes/<int:class_id>/gradebook")
@role_required("supervisor")
def supervisor_gradebook(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """SELECT id, supervisor_id, name, section, archived
               FROM classrooms
               WHERE id = ? AND supervisor_id = ?""",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
            abort(404)

        assignments = conn.execute(
            """SELECT a.id, a.title, a.points, a.due_at,
                      m.activity_type
               FROM classroom_assignments a
               LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
               WHERE a.classroom_id = ?
               ORDER BY a.created_at ASC, a.id ASC""",
            (class_id,),
        ).fetchall()

        students = conn.execute(
            """SELECT u.id, u.username, u.email,
                      COALESCE(p.student_id, '') AS student_number
               FROM classroom_students cs
               JOIN users u ON u.id = cs.student_id
               LEFT JOIN student_profiles p ON p.user_id = u.id
               WHERE cs.classroom_id = ?
               ORDER BY LOWER(u.username), LOWER(u.email), u.id""",
            (class_id,),
        ).fetchall()

        scores = conn.execute(
            """SELECT assignment_id, student_id, score, max_score,
                      percentage, grading_method
               FROM classwork_scores
               WHERE assignment_id IN (
                   SELECT id FROM classroom_assignments WHERE classroom_id = ?
               )""",
            (class_id,),
        ).fetchall()

        score_map = {}
        for score in scores:
            assignment_id = int(_value(score, "assignment_id", 0))
            student_id = int(_value(score, "student_id", 1))
            score_map[(student_id, assignment_id)] = {
                "score": _value(score, "score", 2),
                "max_score": _value(score, "max_score", 3),
                "percentage": _value(score, "percentage", 4),
                "grading_method": _value(score, "grading_method", 5),
            }

        rows = []
        for student in students:
            student_id = int(_value(student, "id", 0))
            cells = []
            earned = 0.0
            possible = 0.0
            graded_count = 0
            for assignment in assignments:
                assignment_id = int(_value(assignment, "id", 0))
                cell = score_map.get((student_id, assignment_id))
                if cell is not None and cell["score"] is not None:
                    score_value = float(cell["score"])
                    max_score = float(cell["max_score"] or _value(assignment, "points", 2, 0) or 0)
                    earned += score_value
                    possible += max_score
                    graded_count += 1
                    cells.append({
                        **cell,
                        "score_display": f"{score_value:g} / {max_score:g}",
                        "percentage_display": f"{float(cell['percentage']):.1f}%" if cell["percentage"] is not None else "—",
                        "graded": True,
                    })
                else:
                    cells.append({
                        "score": None,
                        "max_score": _value(assignment, "points", 2, 0),
                        "percentage": None,
                        "grading_method": None,
                        "score_display": "—",
                        "percentage_display": "—",
                        "graded": False,
                    })

            overall = (earned / possible * 100) if possible else None
            rows.append({
                "id": student_id,
                "name": _value(student, "username", 1, "Student"),
                "email": _value(student, "email", 2, ""),
                "student_number": _value(student, "student_number", 3, ""),
                "cells": cells,
                "earned": earned,
                "possible": possible,
                "graded_count": graded_count,
                "overall": overall,
                "overall_display": f"{overall:.1f}%" if overall is not None else "—",
            })

        assignment_headers = []
        for assignment in assignments:
            assignment_headers.append({
                "id": _value(assignment, "id", 0),
                "title": _value(assignment, "title", 1),
                "points": _value(assignment, "points", 2, 0),
                "activity_type": _value(assignment, "activity_type", 4),
            })

        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 2),
            "section": _value(classroom, "section", 3),
            "archived": _value(classroom, "archived", 4),
        }

        return render_template(
            "classroom/supervisor_gradebook.html",
            classroom=classroom_data,
            assignments=assignment_headers,
            students=rows,
            active_page="classes",
        )
    finally:
        conn.close()
