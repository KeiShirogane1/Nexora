from datetime import datetime

from flask import Blueprint, abort, render_template, session, url_for

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection

student_classwork = Blueprint("student_classwork", __name__)

ACTIVITY_LABELS = {
    "assignment": "Assignment",
    "google_form": "Google Form / Quiz",
    "google_doc": "Google Docs / Sheets",
    "file_reference": "File / Reference",
    "project": "Project",
    "group_project": "Group Project",
}


def _value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        keys = row.keys()
        if key in keys:
            return row[key]
    except AttributeError:
        pass
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return default


def _get_classroom(conn, class_id):
    return conn.execute(
        """SELECT id, name, section, supervisor_id, archived, description
           FROM classrooms WHERE id = ?""",
        (class_id,),
    ).fetchone()


def _is_member(conn, class_id, student_id):
    row = conn.execute(
        """SELECT 1 FROM classroom_students
           WHERE classroom_id = ? AND student_id = ? LIMIT 1""",
        (class_id, student_id),
    ).fetchone()
    return bool(row)


def _assignment_row(conn, class_id, assignment_id):
    return conn.execute(
        """SELECT a.id, a.classroom_id, a.title, a.description, a.due_at,
                  a.points, a.created_at,
                  m.activity_type, m.external_url, m.resource_label,
                  m.resource_filename, m.resource_filepath,
                  m.allow_file_upload, m.group_mode, m.max_group_size
           FROM classroom_assignments a
           LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
           WHERE a.id = ? AND a.classroom_id = ?""",
        (assignment_id, class_id),
    ).fetchone()


def _assignment_data(row):
    activity_type = _value(row, "activity_type", 7, "assignment") or "assignment"
    return {
        "id": _value(row, "id", 0),
        "classroom_id": _value(row, "classroom_id", 1),
        "title": _value(row, "title", 2),
        "description": _value(row, "description", 3),
        "due_at": _value(row, "due_at", 4),
        "points": _value(row, "points", 5, 100),
        "created_at": _value(row, "created_at", 6),
        "activity_type": activity_type,
        "activity_label": ACTIVITY_LABELS.get(activity_type, "Assignment"),
        "external_url": _value(row, "external_url", 8),
        "resource_label": _value(row, "resource_label", 9),
        "resource_filename": _value(row, "resource_filename", 10),
        "resource_filepath": _value(row, "resource_filepath", 11),
        "allow_file_upload": bool(_value(row, "allow_file_upload", 12, 0)),
        "group_mode": bool(_value(row, "group_mode", 13, 0)),
        "max_group_size": _value(row, "max_group_size", 14, 1) or 1,
    }


def _submission_for_student(conn, assignment_id, student_id):
    try:
        return conn.execute(
            """SELECT id, status, grade, feedback, content, filename, filepath, submitted_at
               FROM classroom_submissions
               WHERE assignment_id = ? AND student_id = ?
               ORDER BY id DESC LIMIT 1""",
            (assignment_id, student_id),
        ).fetchone()
    except Exception:
        return None


def _submission_data(row):
    if not row:
        return None
    return {
        "id": _value(row, "id", 0),
        "status": _value(row, "status", 1, "submitted"),
        "grade": _value(row, "grade", 2),
        "feedback": _value(row, "feedback", 3),
        "content": _value(row, "content", 4),
        "filename": _value(row, "filename", 5),
        "filepath": _value(row, "filepath", 6),
        "submitted_at": _value(row, "submitted_at", 7),
    }


@student_classwork.route("/student/classes/<int:class_id>/classwork")
@role_required("student")
def index(class_id):
    student_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = _get_classroom(conn, class_id)
        if not classroom:
            abort(404)
        if not _is_member(conn, class_id, student_id):
            abort(403)

        rows = conn.execute(
            """SELECT a.id, a.classroom_id, a.title, a.description, a.due_at,
                      a.points, a.created_at,
                      m.activity_type, m.external_url, m.resource_label,
                      m.resource_filename, m.resource_filepath,
                      m.allow_file_upload, m.group_mode, m.max_group_size
               FROM classroom_assignments a
               LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
               WHERE a.classroom_id = ?
               ORDER BY CASE WHEN a.due_at IS NULL THEN 1 ELSE 0 END,
                        a.due_at ASC, a.created_at DESC""",
            (class_id,),
        ).fetchall()

        assignments = []
        for row in rows:
            item = _assignment_data(row)
            item["submission"] = _submission_data(
                _submission_for_student(conn, item["id"], student_id)
            )
            assignments.append(item)

        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 1),
            "section": _value(classroom, "section", 2),
            "archived": bool(_value(classroom, "archived", 4, 0)),
            "description": _value(classroom, "description", 5),
        }
    finally:
        conn.close()

    return render_template(
        "classroom/student_classwork.html",
        classroom=classroom_data,
        assignments=assignments,
        active_page="classes",
    )


@student_classwork.route("/student/classes/<int:class_id>/classwork/<int:assignment_id>")
@role_required("student")
def detail(class_id, assignment_id):
    student_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = _get_classroom(conn, class_id)
        if not classroom:
            abort(404)
        if not _is_member(conn, class_id, student_id):
            abort(403)

        row = _assignment_row(conn, class_id, assignment_id)
        if not row:
            abort(404)

        assignment = _assignment_data(row)
        submission = _submission_data(_submission_for_student(conn, assignment_id, student_id))
        past_due = False
        if assignment["due_at"]:
            try:
                due = datetime.fromisoformat(str(assignment["due_at"]).replace("Z", "+00:00"))
                now = datetime.now(due.tzinfo) if due.tzinfo else datetime.now()
                past_due = due < now
            except (ValueError, TypeError):
                past_due = False

        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 1),
            "section": _value(classroom, "section", 2),
            "archived": bool(_value(classroom, "archived", 4, 0)),
        }
    finally:
        conn.close()

    return render_template(
        "classroom/student_classwork_detail.html",
        classroom=classroom_data,
        assignment=assignment,
        submission=submission,
        past_due=past_due,
        active_page="classes",
        submit_url=url_for("classroom.student_submit_assignment", class_id=class_id, assignment_id=assignment_id),
    )
