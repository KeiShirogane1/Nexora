import csv
from io import StringIO

from flask import Blueprint, abort, make_response, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.classwork_grade_calculator import calculate_overall_grade


classwork_gradebook_export = Blueprint("classwork_gradebook_export", __name__)


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


def _build_rows(conn, class_id):
    assignments = conn.execute(
        """SELECT a.id, a.title, a.points
           FROM classroom_assignments a
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
        """SELECT assignment_id, student_id, score, max_score
           FROM classwork_scores
           WHERE assignment_id IN (
               SELECT id FROM classroom_assignments WHERE classroom_id = ?
           )""",
        (class_id,),
    ).fetchall()
    score_map = {
        (int(_value(row, "student_id", 1)), int(_value(row, "assignment_id", 0))): row
        for row in scores
    }

    rows = []
    for student in students:
        student_id = int(_value(student, "id", 0))
        values = []
        graded_scores = []
        for assignment in assignments:
            assignment_id = int(_value(assignment, "id", 0))
            score_row = score_map.get((student_id, assignment_id))
            score = _value(score_row, "score", 2) if score_row is not None else None
            max_score = _value(score_row, "max_score", 3) if score_row is not None else _value(assignment, "points", 2, 0)
            values.append(score)
            if score is not None:
                graded_scores.append({"score": score, "max_score": max_score})

        overall = calculate_overall_grade(graded_scores)
        rows.append({
            "student_number": _value(student, "student_number", 3, ""),
            "name": _value(student, "username", 1, "Student"),
            "email": _value(student, "email", 2, ""),
            "values": values,
            "overall": overall,
        })
    return assignments, rows


@classwork_gradebook_export.route("/supervisor/classes/<int:class_id>/gradebook/export.csv")
@role_required("supervisor")
def export_supervisor_gradebook(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            "SELECT id, name, section FROM classrooms WHERE id = ? AND supervisor_id = ?",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
            abort(404)

        assignments, rows = _build_rows(conn, class_id)
    finally:
        conn.close()

    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Student Number", "Student", "Email", *[a["title"] if hasattr(a, "keys") else a[1] for a in assignments], "Overall %"])
    for row in rows:
        writer.writerow([
            row["student_number"],
            row["name"],
            row["email"],
            *["" if score is None else score for score in row["values"]],
            "" if row["overall"] is None else f"{row['overall']:.1f}",
        ])

    filename = f"gradebook-{_value(classroom, 'name', 1, 'class').strip().replace(' ', '-')}.csv"
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
