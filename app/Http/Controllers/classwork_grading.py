from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection

classwork_grading = Blueprint("classwork_grading", __name__)


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


def _assignment(conn, class_id, assignment_id, supervisor_id):
    return conn.execute(
        """SELECT a.id, a.classroom_id, a.title, a.description, a.due_at, a.points,
                  c.name AS classroom_name, m.team_name,
                  COALESCE(m.submission_mode, 'individual') AS submission_mode
           FROM classroom_assignments a
           JOIN classrooms c ON c.id = a.classroom_id
           LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
           WHERE a.id = ? AND a.classroom_id = ? AND c.supervisor_id = ?""",
        (assignment_id, class_id, supervisor_id),
    ).fetchone()


def _submission(conn, assignment_id, submission_id):
    return conn.execute(
        """SELECT s.id, s.assignment_id, s.student_id, s.attempt_no, s.content,
                  s.status, s.submitted_at, s.grade, s.feedback,
                  COALESCE(s.is_team_submission, 0) AS is_team_submission,
                  u.username, u.email
           FROM classwork_submissions s
           JOIN users u ON u.id = s.student_id
           WHERE s.id = ? AND s.assignment_id = ?""",
        (submission_id, assignment_id),
    ).fetchone()


def _files(conn, submission_id):
    return conn.execute(
        """SELECT id, original_filename, stored_filename, relative_path, mime_type, size_bytes
           FROM classwork_submission_files
           WHERE submission_id = ? ORDER BY id""",
        (submission_id,),
    ).fetchall()


def _team_members(conn, assignment_id):
    return conn.execute(
        """SELECT u.id, u.username, u.email
           FROM classroom_assignment_recipients ar
           JOIN users u ON u.id = ar.student_id
           WHERE ar.assignment_id = ?
           ORDER BY LOWER(u.username), LOWER(u.email), u.id""",
        (assignment_id,),
    ).fetchall()


def _students_with_submissions(conn, class_id, assignment_id):
    return conn.execute(
        """SELECT u.id AS student_id, u.username, u.email,
                  s.id AS submission_id, s.attempt_no, s.status, s.submitted_at, s.grade
           FROM classroom_students cs
           JOIN users u ON u.id = cs.student_id
           LEFT JOIN classwork_submissions s
             ON s.student_id = u.id AND s.assignment_id = ?
            AND COALESCE(s.is_team_submission, 0) = 0
            AND s.attempt_no = (
                SELECT MAX(s2.attempt_no) FROM classwork_submissions s2
                WHERE s2.assignment_id = ? AND s2.student_id = u.id
                  AND COALESCE(s2.is_team_submission, 0) = 0
            )
           WHERE cs.classroom_id = ?
             AND (
                 NOT EXISTS (
                     SELECT 1 FROM classroom_assignment_recipients all_recipients
                     WHERE all_recipients.assignment_id = ?
                 )
                 OR EXISTS (
                     SELECT 1 FROM classroom_assignment_recipients assigned_recipient
                     WHERE assigned_recipient.assignment_id = ?
                       AND assigned_recipient.student_id = u.id
                 )
             )
           ORDER BY LOWER(u.username), LOWER(u.email)""",
        (assignment_id, assignment_id, class_id, assignment_id, assignment_id),
    ).fetchall()


@classwork_grading.route("/supervisor/classes/<int:class_id>/classwork/<int:assignment_id>/submissions/<int:submission_id>/review")
@role_required("supervisor")
def review(class_id, assignment_id, submission_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        assignment = _assignment(conn, class_id, assignment_id, supervisor_id)
        if not assignment:
            abort(404)
        submission = _submission(conn, assignment_id, submission_id)
        if not submission:
            abort(404)
        member = conn.execute(
            "SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ? LIMIT 1",
            (class_id, _value(submission, "student_id", 2)),
        ).fetchone()
        if not member:
            abort(404)
        files = _files(conn, submission_id)
        is_team_submission = bool(_value(submission, "is_team_submission", 9, 0))
        team_members = _team_members(conn, assignment_id) if is_team_submission else []
        return render_template(
            "classroom/supervisor_classwork_review.html",
            assignment=assignment,
            submission=submission,
            files=files,
            team_members=team_members,
            is_team_submission=is_team_submission,
            active_page="classes",
        )
    finally:
        conn.close()


@classwork_grading.route("/supervisor/classes/<int:class_id>/classwork/<int:assignment_id>/submissions/<int:submission_id>/grade", methods=["POST"])
@role_required("supervisor")
def grade(class_id, assignment_id, submission_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        assignment = _assignment(conn, class_id, assignment_id, supervisor_id)
        if not assignment:
            abort(404)
        submission = _submission(conn, assignment_id, submission_id)
        if not submission:
            abort(404)
        member = conn.execute(
            "SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ? LIMIT 1",
            (class_id, _value(submission, "student_id", 2)),
        ).fetchone()
        if not member:
            abort(404)

        raw_grade = (request.form.get("grade") or "").strip()
        feedback = (request.form.get("feedback") or "").strip()
        action = request.form.get("action", "save")
        if raw_grade == "":
            flash("Enter a grade before saving.", "danger")
            return redirect(url_for("classwork_grading.review", class_id=class_id, assignment_id=assignment_id, submission_id=submission_id))
        try:
            grade_value = float(raw_grade)
        except ValueError:
            flash("Grade must be a number.", "danger")
            return redirect(url_for("classwork_grading.review", class_id=class_id, assignment_id=assignment_id, submission_id=submission_id))

        points = float(_value(assignment, "points", 5, 0) or 0)
        if grade_value < 0 or grade_value > points:
            flash(f"Grade must be between 0 and {points:g}.", "danger")
            return redirect(url_for("classwork_grading.review", class_id=class_id, assignment_id=assignment_id, submission_id=submission_id))

        stored_grade = int(grade_value) if grade_value.is_integer() else grade_value
        conn.execute(
            "UPDATE classwork_submissions SET grade = ?, feedback = ?, status = 'graded' WHERE id = ? AND assignment_id = ?",
            (stored_grade, feedback or None, submission_id, assignment_id),
        )

        submitted_by_id = int(_value(submission, "student_id", 2))
        is_team_submission = bool(_value(submission, "is_team_submission", 9, 0))
        shared_mode = (_value(assignment, "submission_mode", 8, "individual") or "individual") == "shared"
        if is_team_submission and shared_mode:
            team_rows = _team_members(conn, assignment_id)
            target_student_ids = [int(_value(row, "id", 0)) for row in team_rows]
            if not target_student_ids:
                target_student_ids = [submitted_by_id]
        else:
            target_student_ids = [submitted_by_id]

        max_score = float(points)
        percentage = (float(grade_value) / max_score * 100) if max_score else 0
        for student_id in target_student_ids:
            conn.execute(
                """INSERT INTO classwork_scores
                   (assignment_id, student_id, score, max_score, percentage, grading_method)
                   VALUES (?, ?, ?, ?, ?, 'manual')
                   ON CONFLICT(assignment_id, student_id) DO UPDATE SET
                       score = excluded.score,
                       max_score = excluded.max_score,
                       percentage = excluded.percentage,
                       grading_method = 'manual',
                       imported_at = CURRENT_TIMESTAMP""",
                (assignment_id, student_id, float(grade_value), max_score, percentage),
            )
        conn.commit()
        flash(
            "Team grade saved for all selected members."
            if is_team_submission and shared_mode else
            "Grade saved successfully.",
            "success",
        )

        if action == "next" and not is_team_submission:
            rows = _students_with_submissions(conn, class_id, assignment_id)
            ids = [int(_value(r, "submission_id", 3)) for r in rows if _value(r, "submission_id", 3) is not None]
            try:
                position = ids.index(submission_id)
                next_id = ids[position + 1] if position + 1 < len(ids) else None
            except ValueError:
                next_id = None
            if next_id:
                return redirect(url_for("classwork_grading.review", class_id=class_id, assignment_id=assignment_id, submission_id=next_id))
        return redirect(url_for("classwork_submissions.supervisor_submissions", class_id=class_id, assignment_id=assignment_id))
    finally:
        conn.close()


@classwork_grading.route("/supervisor/classes/<int:class_id>/classwork/<int:assignment_id>/submissions/<int:submission_id>/return", methods=["POST"])
@role_required("supervisor")
def return_for_revision(class_id, assignment_id, submission_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        assignment = _assignment(conn, class_id, assignment_id, supervisor_id)
        if not assignment:
            abort(404)
        submission = _submission(conn, assignment_id, submission_id)
        if not submission:
            abort(404)
        reason = (request.form.get("feedback") or "").strip()
        conn.execute(
            "UPDATE classwork_submissions SET status = 'resubmission_required', feedback = ? WHERE id = ? AND assignment_id = ?",
            (reason or None, submission_id, assignment_id),
        )
        conn.commit()
        flash(
            "Team submission returned for revision."
            if bool(_value(submission, "is_team_submission", 9, 0)) else
            "Submission returned to the intern for revision.",
            "success",
        )
        return redirect(url_for("classwork_grading.review", class_id=class_id, assignment_id=assignment_id, submission_id=submission_id))
    finally:
        conn.close()


@classwork_grading.route("/supervisor/classes/<int:class_id>/classwork/<int:assignment_id>/submissions/<int:submission_id>/file/<int:file_id>")
@role_required("supervisor")
def supervisor_file(class_id, assignment_id, submission_id, file_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        if not _assignment(conn, class_id, assignment_id, supervisor_id):
            abort(404)
        row = conn.execute(
            """SELECT f.relative_path, f.original_filename
               FROM classwork_submission_files f
               JOIN classwork_submissions s ON s.id = f.submission_id
               WHERE f.id = ? AND f.submission_id = ? AND s.assignment_id = ?""",
            (file_id, submission_id, assignment_id),
        ).fetchone()
        if not row:
            abort(404)
        relative = Path(_value(row, "relative_path", 0))
        root = Path(current_app.config["UPLOAD_FOLDER"])
        return send_from_directory(str(root / relative.parent), relative.name, as_attachment=False, download_name=_value(row, "original_filename", 1))
    finally:
        conn.close()
