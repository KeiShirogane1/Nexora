from flask import Blueprint, abort, render_template, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection

student_gradebook = Blueprint("student_gradebook", __name__)


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


def _activity_label(activity_type):
    return {
        "assignment": "Assignment",
        "google_form": "Google Form / Quiz",
        "google_doc": "Google Docs / Sheets",
        "file_reference": "File / Reference",
        "project": "Project",
        "group_project": "Group Project",
    }.get(activity_type or "assignment", "Assignment")


@student_gradebook.route("/student/classes/<int:class_id>/gradebook")
@role_required("student")
def gradebook(class_id):
    student_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """SELECT c.id, c.name, c.section, c.supervisor_id, c.archived,
                      u.username AS supervisor_name
               FROM classrooms c
               JOIN users u ON u.id = c.supervisor_id
               JOIN classroom_students cs ON cs.classroom_id = c.id
               WHERE c.id = ? AND cs.student_id = ?""",
            (class_id, student_id),
        ).fetchone()
        if not classroom:
            abort(404)

        assignments = conn.execute(
            """SELECT a.id, a.title, a.points, a.due_at, a.created_at,
                      m.activity_type
               FROM classroom_assignments a
               LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
               WHERE a.classroom_id = ?
               ORDER BY a.created_at ASC, a.id ASC""",
            (class_id,),
        ).fetchall()

        scores = conn.execute(
            """SELECT assignment_id, score, max_score, percentage, grading_method
               FROM classwork_scores
               WHERE student_id = ?
                 AND assignment_id IN (
                     SELECT id FROM classroom_assignments WHERE classroom_id = ?
                 )""",
            (student_id, class_id),
        ).fetchall()
        score_map = {
            int(_value(row, "assignment_id", 0)): row for row in scores
        }

        activities = []
        earned = 0.0
        possible = 0.0
        graded_count = 0
        for assignment in assignments:
            assignment_id = int(_value(assignment, "id", 0))
            points = float(_value(assignment, "points", 2, 0) or 0)
            score_row = score_map.get(assignment_id)
            if score_row is not None and _value(score_row, "score", 1) is not None:
                score = float(_value(score_row, "score", 1))
                max_score = float(_value(score_row, "max_score", 2, points) or points)
                percentage = _value(score_row, "percentage", 3)
                if percentage is None:
                    percentage = (score / max_score * 100) if max_score else 0
                earned += score
                possible += max_score
                graded_count += 1
                graded = True
                score_display = f"{score:g} / {max_score:g}"
                percentage_display = f"{float(percentage):.1f}%"
                grading_method = _value(score_row, "grading_method", 4) or "manual"
            else:
                graded = False
                score_display = "—"
                percentage_display = "—"
                grading_method = None

            activities.append({
                "id": assignment_id,
                "title": _value(assignment, "title", 1, "Activity"),
                "activity_label": _activity_label(_value(assignment, "activity_type", 5)),
                "due_at": _value(assignment, "due_at", 3),
                "points": points,
                "graded": graded,
                "score_display": score_display,
                "percentage_display": percentage_display,
                "grading_method": grading_method,
            })

        overall = (earned / possible * 100) if possible else None
        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 1),
            "section": _value(classroom, "section", 2),
            "supervisor": _value(classroom, "supervisor_name", 5),
            "archived": bool(_value(classroom, "archived", 4, 0)),
        }
    finally:
        conn.close()

    return render_template(
        "classroom/student_gradebook.html",
        classroom=classroom_data,
        activities=activities,
        graded_count=graded_count,
        total_count=len(activities),
        earned=earned,
        possible=possible,
        overall=overall,
        overall_display=f"{overall:.1f}%" if overall is not None else "—",
        active_page="classes",
    )
