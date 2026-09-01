import os
import secrets
from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection

classwork_submissions = Blueprint("classwork_submissions", __name__)

ALLOWED_EXTENSIONS = {
    "jpg", "jpeg", "png", "webp", "pdf", "doc", "docx", "ppt", "pptx",
    "xls", "xlsx", "txt", "zip"
}
MAX_FILES_PER_SUBMISSION = 10


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


def _is_member(conn, class_id, student_id):
    return conn.execute(
        "SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ? LIMIT 1",
        (class_id, student_id),
    ).fetchone() is not None


def _assignment(conn, class_id, assignment_id):
    return conn.execute(
        """SELECT a.id, a.classroom_id, a.title, a.description, a.due_at, a.points,
                  m.activity_type, m.allow_file_upload, m.group_mode, m.max_group_size
           FROM classroom_assignments a
           LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
           WHERE a.id = ? AND a.classroom_id = ?""",
        (assignment_id, class_id),
    ).fetchone()


def _safe_extension(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _submission(conn, assignment_id, student_id):
    return conn.execute(
        """SELECT id, attempt_no, status, submitted_at, grade, feedback
           FROM classwork_submissions
           WHERE assignment_id = ? AND student_id = ?
           ORDER BY attempt_no DESC LIMIT 1""",
        (assignment_id, student_id),
    ).fetchone()


def _submission_data(conn, row):
    if not row:
        return None
    submission_id = _value(row, "id", 0)
    files = conn.execute(
        """SELECT id, original_filename, stored_filename, mime_type, size_bytes
           FROM classwork_submission_files
           WHERE submission_id = ? ORDER BY id""",
        (submission_id,),
    ).fetchall()
    return {
        "id": submission_id,
        "attempt_no": _value(row, "attempt_no", 1),
        "status": _value(row, "status", 2, "submitted"),
        "submitted_at": _value(row, "submitted_at", 3),
        "grade": _value(row, "grade", 4),
        "feedback": _value(row, "feedback", 5),
        "files": [
            {
                "id": _value(f, "id", 0),
                "filename": _value(f, "original_filename", 1),
                "stored_filename": _value(f, "stored_filename", 2),
                "mime_type": _value(f, "mime_type", 3),
                "size_bytes": _value(f, "size_bytes", 4),
            }
            for f in files
        ],
    }


def _classroom(conn, class_id):
    return conn.execute(
        "SELECT id, name, section, archived FROM classrooms WHERE id = ?",
        (class_id,),
    ).fetchone()


@classwork_submissions.route("/student/classes/<int:class_id>/classwork/<int:assignment_id>/submit", methods=["POST"])
@role_required("student")
def submit(class_id, assignment_id):
    student_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = _classroom(conn, class_id)
        if not classroom:
            abort(404)
        if not _is_member(conn, class_id, student_id):
            abort(403)

        assignment = _assignment(conn, class_id, assignment_id)
        if not assignment:
            abort(404)

        allow_upload = bool(_value(assignment, "allow_file_upload", 7, 0))
        if not allow_upload:
            flash("This classwork does not accept file submissions.", "warning")
            return redirect(url_for("student_classwork.detail", class_id=class_id, assignment_id=assignment_id))

        uploaded = [f for f in request.files.getlist("files") if f and f.filename]
        content = (request.form.get("content") or "").strip()
        if not uploaded and not content:
            flash("Add at least one file or a written response before submitting.", "danger")
            return redirect(url_for("student_classwork.detail", class_id=class_id, assignment_id=assignment_id))
        if len(uploaded) > MAX_FILES_PER_SUBMISSION:
            flash(f"You can submit up to {MAX_FILES_PER_SUBMISSION} files at once.", "danger")
            return redirect(url_for("student_classwork.detail", class_id=class_id, assignment_id=assignment_id))

        for item in uploaded:
            if not _safe_extension(item.filename):
                flash(f"Unsupported file type: {item.filename}", "danger")
                return redirect(url_for("student_classwork.detail", class_id=class_id, assignment_id=assignment_id))

        previous = _submission(conn, assignment_id, student_id)
        attempt_no = (_value(previous, "attempt_no", 1, 0) or 0) + 1
        now = datetime.utcnow().isoformat(timespec="seconds")
        due_at = _value(assignment, "due_at", 4)
        status = "late" if due_at and str(due_at) < now else "submitted"

        conn.execute(
            """INSERT INTO classwork_submissions
               (assignment_id, student_id, attempt_no, content, status, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assignment_id, student_id, attempt_no, content or None, status, now),
        )
        row = conn.execute(
            """SELECT id FROM classwork_submissions
               WHERE assignment_id = ? AND student_id = ? AND attempt_no = ?""",
            (assignment_id, student_id, attempt_no),
        ).fetchone()
        submission_id = _value(row, "id", 0)

        base = Path(current_app.config["UPLOAD_FOLDER"]) / "classwork_submissions" / str(class_id) / str(assignment_id) / str(student_id) / str(submission_id)
        base.mkdir(parents=True, exist_ok=True)

        for item in uploaded:
            original = secure_filename(item.filename) or "submission"
            ext = Path(original).suffix.lower()
            stored = f"{secrets.token_hex(16)}{ext}"
            destination = base / stored
            item.save(destination)
            size = destination.stat().st_size
            conn.execute(
                """INSERT INTO classwork_submission_files
                   (submission_id, original_filename, stored_filename, relative_path, mime_type, size_bytes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    submission_id,
                    original,
                    stored,
                    str(destination.relative_to(Path(current_app.config["UPLOAD_FOLDER"]))),
                    item.mimetype or "application/octet-stream",
                    size,
                ),
            )

        conn.commit()
        flash("Your work was submitted successfully.", "success")
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f"Unable to submit your work: {exc}", "danger")
    finally:
        conn.close()

    return redirect(url_for("student_classwork.detail", class_id=class_id, assignment_id=assignment_id))


@classwork_submissions.route("/student/classes/<int:class_id>/classwork/<int:assignment_id>/submission-file/<int:file_id>")
@role_required("student")
def student_file(class_id, assignment_id, file_id):
    student_id = session["user_id"]
    conn = get_db_connection()
    try:
        if not _is_member(conn, class_id, student_id):
            abort(403)
        row = conn.execute(
            """SELECT f.relative_path, f.original_filename
               FROM classwork_submission_files f
               JOIN classwork_submissions s ON s.id = f.submission_id
               WHERE f.id = ? AND s.assignment_id = ? AND s.student_id = ?""",
            (file_id, assignment_id, student_id),
        ).fetchone()
        if not row:
            abort(404)
        relative = Path(_value(row, "relative_path", 0))
        root = Path(current_app.config["UPLOAD_FOLDER"])
        return send_from_directory(str(root / relative.parent), relative.name, as_attachment=False, download_name=_value(row, "original_filename", 1))
    finally:
        conn.close()


@classwork_submissions.route("/supervisor/classes/<int:class_id>/classwork/<int:assignment_id>/submissions")
@role_required("supervisor")
def supervisor_submissions(class_id, assignment_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        assignment = conn.execute(
            """SELECT a.id, a.classroom_id, a.title, a.points
               FROM classroom_assignments a
               JOIN classrooms c ON c.id = a.classroom_id
               WHERE a.id = ? AND a.classroom_id = ? AND c.supervisor_id = ?""",
            (assignment_id, class_id, supervisor_id),
        ).fetchone()
        if not assignment:
            abort(404)

        students = conn.execute(
            """SELECT u.id, u.username, u.email,
                      s.id AS submission_id, s.attempt_no, s.status, s.submitted_at, s.grade
               FROM classroom_students cs
               JOIN users u ON u.id = cs.student_id
               LEFT JOIN classwork_submissions s
                 ON s.student_id = u.id AND s.assignment_id = ?
                AND s.attempt_no = (SELECT MAX(s2.attempt_no) FROM classwork_submissions s2
                                    WHERE s2.assignment_id = ? AND s2.student_id = u.id)
               WHERE cs.classroom_id = ?
               ORDER BY LOWER(u.username), LOWER(u.email)""",
            (assignment_id, assignment_id, class_id),
        ).fetchall()
        rows = []
        for row in students:
            rows.append({
                "id": _value(row, "id", 0),
                "username": _value(row, "username", 1),
                "email": _value(row, "email", 2),
                "submission_id": _value(row, "submission_id", 3),
                "attempt_no": _value(row, "attempt_no", 4),
                "status": _value(row, "status", 5, "not_submitted"),
                "submitted_at": _value(row, "submitted_at", 6),
                "grade": _value(row, "grade", 7),
            })
    finally:
        conn.close()
    return render_template("classroom/supervisor_classwork_submissions.html", assignment=assignment, students=rows, active_page="classes")
