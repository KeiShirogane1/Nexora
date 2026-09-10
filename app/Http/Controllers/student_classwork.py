from datetime import datetime

from flask import Blueprint, abort, render_template, session, url_for

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection

student_classwork = Blueprint("student_classwork", __name__)

ACTIVITY_LABELS = {
    "assignment": "Task",
    "google_form": "Form / Assessment",
    "google_doc": "Online Work",
    "file_reference": "Resource",
    "project": "Project",
    "group_project": "Team Task",
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
        """SELECT c.id, c.name, c.section, c.supervisor_id, c.archived,
                  c.description, c.code, u.username AS supervisor_name
           FROM classrooms c
           JOIN users u ON u.id = c.supervisor_id
           WHERE c.id = ?""",
        (class_id,),
    ).fetchone()


def _is_member(conn, class_id, student_id):
    row = conn.execute(
        """SELECT 1 FROM classroom_students
           WHERE classroom_id = ? AND student_id = ? LIMIT 1""",
        (class_id, student_id),
    ).fetchone()
    return bool(row)


def _has_assignment_access(conn, assignment_id, student_id):
    count_row = conn.execute(
        "SELECT COUNT(*) FROM classroom_assignment_recipients WHERE assignment_id = ?",
        (assignment_id,),
    ).fetchone()
    recipient_count = count_row[0] if count_row else 0
    if not recipient_count:
        return True
    return conn.execute(
        """SELECT 1 FROM classroom_assignment_recipients
           WHERE assignment_id = ? AND student_id = ? LIMIT 1""",
        (assignment_id, student_id),
    ).fetchone() is not None


def _team_members(conn, class_id, assignment_id):
    rows = conn.execute(
        """SELECT u.id, u.username, u.email
           FROM classroom_assignment_recipients ar
           JOIN users u ON u.id = ar.student_id
           WHERE ar.assignment_id = ?
           ORDER BY LOWER(u.username), LOWER(u.email), u.id""",
        (assignment_id,),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            """SELECT u.id, u.username, u.email
               FROM classroom_students cs
               JOIN users u ON u.id = cs.student_id
               WHERE cs.classroom_id = ?
               ORDER BY LOWER(u.username), LOWER(u.email), u.id""",
            (class_id,),
        ).fetchall()
    return [
        {
            "id": _value(row, "id", 0),
            "username": _value(row, "username", 1),
            "email": _value(row, "email", 2),
        }
        for row in rows
    ]


def _assignment_row(conn, class_id, assignment_id):
    return conn.execute(
        """SELECT a.id, a.classroom_id, a.title, a.description, a.due_at,
                  a.points, a.created_at,
                  m.activity_type, m.external_url, m.resource_label,
                  m.resource_filename, m.resource_filepath,
                  m.allow_file_upload, m.group_mode, m.max_group_size, m.team_name,
                  COALESCE(m.submission_mode, 'individual') AS submission_mode
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
        "activity_label": ACTIVITY_LABELS.get(activity_type, "Task"),
        "external_url": _value(row, "external_url", 8),
        "resource_label": _value(row, "resource_label", 9),
        "resource_filename": _value(row, "resource_filename", 10),
        "resource_filepath": _value(row, "resource_filepath", 11),
        "allow_file_upload": bool(_value(row, "allow_file_upload", 12, 0)),
        "group_mode": bool(_value(row, "group_mode", 13, 0)),
        "max_group_size": _value(row, "max_group_size", 14, 1) or 1,
        "team_name": _value(row, "team_name", 15, "") or "",
        "submission_mode": _value(row, "submission_mode", 16, "individual") or "individual",
    }


def _modern_submission(conn, assignment_id, student_id, shared=False):
    if shared:
        row = conn.execute(
            """SELECT s.id, s.attempt_no, s.status, s.grade, s.feedback, s.content,
                      s.submitted_at, s.student_id, u.username AS submitted_by_username,
                      COALESCE(s.is_team_submission, 0) AS is_team_submission
               FROM classwork_submissions s
               JOIN users u ON u.id = s.student_id
               WHERE s.assignment_id = ? AND COALESCE(s.is_team_submission, 0) = 1
               ORDER BY s.attempt_no DESC, s.id DESC LIMIT 1""",
            (assignment_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT s.id, s.attempt_no, s.status, s.grade, s.feedback, s.content,
                      s.submitted_at, s.student_id, u.username AS submitted_by_username,
                      COALESCE(s.is_team_submission, 0) AS is_team_submission
               FROM classwork_submissions s
               JOIN users u ON u.id = s.student_id
               WHERE s.assignment_id = ? AND s.student_id = ?
                 AND COALESCE(s.is_team_submission, 0) = 0
               ORDER BY s.attempt_no DESC, s.id DESC LIMIT 1""",
            (assignment_id, student_id),
        ).fetchone()
    if not row:
        return None

    submission_id = _value(row, "id", 0)
    files = conn.execute(
        """SELECT id, original_filename, mime_type, size_bytes
           FROM classwork_submission_files
           WHERE submission_id = ? ORDER BY id""",
        (submission_id,),
    ).fetchall()
    return {
        "id": submission_id,
        "attempt_no": _value(row, "attempt_no", 1, 1) or 1,
        "status": _value(row, "status", 2, "submitted") or "submitted",
        "grade": _value(row, "grade", 3),
        "feedback": _value(row, "feedback", 4),
        "content": _value(row, "content", 5),
        "submitted_at": _value(row, "submitted_at", 6),
        "submitted_by_id": _value(row, "student_id", 7),
        "submitted_by_username": _value(row, "submitted_by_username", 8),
        "is_team_submission": bool(_value(row, "is_team_submission", 9, 0)),
        "source": "classwork",
        "files": [
            {
                "id": _value(file_row, "id", 0),
                "filename": _value(file_row, "original_filename", 1),
                "mime_type": _value(file_row, "mime_type", 2),
                "size_bytes": _value(file_row, "size_bytes", 3),
            }
            for file_row in files
        ],
    }


def _legacy_submission(conn, assignment_id, student_id):
    row = conn.execute(
        """SELECT id, status, grade, feedback, content, filename, filepath, submitted_at
           FROM classroom_submissions
           WHERE assignment_id = ? AND student_id = ?
           ORDER BY id DESC LIMIT 1""",
        (assignment_id, student_id),
    ).fetchone()
    if not row:
        return None
    return {
        "id": _value(row, "id", 0),
        "attempt_no": 1,
        "status": _value(row, "status", 1, "submitted") or "submitted",
        "grade": _value(row, "grade", 2),
        "feedback": _value(row, "feedback", 3),
        "content": _value(row, "content", 4),
        "filename": _value(row, "filename", 5),
        "filepath": _value(row, "filepath", 6),
        "submitted_at": _value(row, "submitted_at", 7),
        "submitted_by_id": student_id,
        "submitted_by_username": None,
        "is_team_submission": False,
        "source": "legacy",
        "files": [],
    }


def _submission_for_student(conn, assignment, student_id):
    shared = assignment.get("submission_mode") == "shared"
    modern = _modern_submission(conn, assignment["id"], student_id, shared=shared)
    if modern:
        return modern
    if shared:
        return None
    return _legacy_submission(conn, assignment["id"], student_id)


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
                      m.allow_file_upload, m.group_mode, m.max_group_size, m.team_name,
                      COALESCE(m.submission_mode, 'individual') AS submission_mode
               FROM classroom_assignments a
               LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
               WHERE a.classroom_id = ?
                 AND (
                     NOT EXISTS (
                         SELECT 1 FROM classroom_assignment_recipients all_recipients
                         WHERE all_recipients.assignment_id = a.id
                     )
                     OR EXISTS (
                         SELECT 1 FROM classroom_assignment_recipients my_recipient
                         WHERE my_recipient.assignment_id = a.id
                           AND my_recipient.student_id = ?
                     )
                 )
               ORDER BY CASE WHEN a.due_at IS NULL THEN 1 ELSE 0 END,
                        a.due_at ASC, a.created_at DESC""",
            (class_id, student_id),
        ).fetchall()

        assignments = []
        for row in rows:
            item = _assignment_data(row)
            item["submission"] = _submission_for_student(conn, item, student_id)
            item["team_members"] = (
                _team_members(conn, class_id, item["id"])
                if item["activity_type"] == "group_project" or item["group_mode"]
                else []
            )
            assignments.append(item)

        archived = bool(_value(classroom, "archived", 4, 0))
        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 1),
            "section": _value(classroom, "section", 2),
            "archived": archived,
            "description": _value(classroom, "description", 5),
            "code": _value(classroom, "code", 6),
            "supervisor": _value(classroom, "supervisor_name", 7),
            "status": "Archived" if archived else "Active",
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
        if not _has_assignment_access(conn, assignment_id, student_id):
            abort(403)

        assignment = _assignment_data(row)
        assignment["team_members"] = (
            _team_members(conn, class_id, assignment_id)
            if assignment["activity_type"] == "group_project" or assignment["group_mode"]
            else []
        )
        submission = _submission_for_student(conn, assignment, student_id)
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
        submit_url=url_for("classwork_submissions.submit", class_id=class_id, assignment_id=assignment_id),
    )
