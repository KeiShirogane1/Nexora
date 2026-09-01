from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.classwork_score_import_service import allowed_import, normalize_rows, parse_file

classwork_scores = Blueprint("classwork_scores", __name__)


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
        """SELECT a.id, a.classroom_id, a.title, a.points, c.name AS class_name
           FROM classroom_assignments a
           JOIN classrooms c ON c.id = a.classroom_id
           WHERE a.id = ? AND a.classroom_id = ? AND c.supervisor_id = ?""",
        (assignment_id, class_id, supervisor_id),
    ).fetchone()


def _students(conn, class_id):
    return conn.execute(
        """SELECT u.id, u.username, u.email,
                  COALESCE(p.student_id, '') AS student_number
           FROM classroom_students cs
           JOIN users u ON u.id = cs.student_id
           LEFT JOIN student_profiles p ON p.user_id = u.id
           WHERE cs.classroom_id = ?
           ORDER BY LOWER(u.username), LOWER(u.email)""",
        (class_id,),
    ).fetchall()


def _match_student(row, students):
    student_id = (row.student_id or "").strip().lower()
    email = (row.email or "").strip().lower()
    name = (row.name or "").strip().lower()

    if student_id:
        matches = [s for s in students if str(_value(s, "student_number", 3, "")).strip().lower() == student_id]
        if len(matches) == 1:
            return matches[0], "student_id"
    if email:
        matches = [s for s in students if str(_value(s, "email", 2, "")).strip().lower() == email]
        if len(matches) == 1:
            return matches[0], "email"
    if name:
        matches = [s for s in students if str(_value(s, "username", 1, "")).strip().lower() == name]
        if len(matches) == 1:
            return matches[0], "name"
    return None, None


@classwork_scores.route("/supervisor/classes/<int:class_id>/classwork/<int:assignment_id>/import", methods=["GET", "POST"])
@role_required("supervisor")
def import_scores(class_id, assignment_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        assignment = _assignment(conn, class_id, assignment_id, supervisor_id)
        if not assignment:
            abort(404)
        students = _students(conn, class_id)

        if request.method == "GET":
            return render_template(
                "classroom/supervisor_classwork_import.html",
                assignment=assignment,
                preview=None,
                columns={},
                active_page="classes",
            )

        upload = request.files.get("score_file")
        if not upload or not upload.filename:
            flash("Choose a CSV or XLSX file.", "danger")
            return redirect(url_for("classwork_scores.import_scores", class_id=class_id, assignment_id=assignment_id))
        if not allowed_import(upload.filename):
            flash("Only CSV and XLSX score files are supported.", "danger")
            return redirect(url_for("classwork_scores.import_scores", class_id=class_id, assignment_id=assignment_id))

        try:
            data = upload.read()
            headers, raw_rows = parse_file(upload.filename, data)
            columns, normalized = normalize_rows(headers, raw_rows)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("classwork_scores.import_scores", class_id=class_id, assignment_id=assignment_id))

        preview = []
        unmatched = 0
        invalid_scores = 0
        seen = set()
        max_points = float(_value(assignment, "points", 3, 0) or 0)

        for row in normalized:
            matched, matched_by = _match_student(row, students)
            score_ok = row.score is not None and 0 <= row.score <= max_points
            duplicate = False
            matched_id = _value(matched, "id", 0) if matched else None
            if matched_id is not None:
                duplicate = matched_id in seen
                seen.add(matched_id)
            if not matched:
                unmatched += 1
            if not score_ok:
                invalid_scores += 1
            preview.append({
                "name": row.name or "",
                "email": row.email or "",
                "student_id": row.student_id or "",
                "score": row.score,
                "matched_student_id": matched_id,
                "matched_name": _value(matched, "username", 1) if matched else None,
                "matched_by": matched_by,
                "score_ok": score_ok,
                "duplicate": duplicate,
            })

        valid = all(item["matched_student_id"] is not None and item["score_ok"] and not item["duplicate"] for item in preview)
        return render_template(
            "classroom/supervisor_classwork_import.html",
            assignment=assignment,
            preview=preview,
            columns=columns,
            total_rows=len(preview),
            unmatched=unmatched,
            invalid_scores=invalid_scores,
            valid=valid,
            active_page="classes",
        )
    finally:
        conn.close()


@classwork_scores.route("/supervisor/classes/<int:class_id>/classwork/<int:assignment_id>/import/commit", methods=["POST"])
@role_required("supervisor")
def commit_import(class_id, assignment_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        assignment = _assignment(conn, class_id, assignment_id, supervisor_id)
        if not assignment:
            abort(404)
        students = _students(conn, class_id)
        upload = request.files.get("score_file")
        if not upload or not upload.filename or not allowed_import(upload.filename):
            flash("Please upload the same CSV/XLSX file again to complete the import.", "danger")
            return redirect(url_for("classwork_scores.import_scores", class_id=class_id, assignment_id=assignment_id))

        headers, raw_rows = parse_file(upload.filename, upload.read())
        _, normalized = normalize_rows(headers, raw_rows)
        max_points = float(_value(assignment, "points", 3, 0) or 0)
        seen = set()
        records = []
        for row in normalized:
            matched, _ = _match_student(row, students)
            matched_id = _value(matched, "id", 0) if matched else None
            if matched_id is None or row.score is None or row.score < 0 or row.score > max_points or matched_id in seen:
                flash("Import failed validation. No scores were saved.", "danger")
                return redirect(url_for("classwork_scores.import_scores", class_id=class_id, assignment_id=assignment_id))
            seen.add(matched_id)
            records.append((int(matched_id), row.score))

        for student_id, score in records:
            existing = conn.execute(
                """SELECT id FROM classroom_submissions
                   WHERE assignment_id = ? AND student_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (assignment_id, student_id),
            ).fetchone()
            now = datetime.utcnow().isoformat(timespec="seconds")
            if existing:
                conn.execute(
                    """UPDATE classroom_submissions
                       SET grade = ?, status = 'graded', submitted_at = COALESCE(submitted_at, ?)
                       WHERE id = ?""",
                    (score, now, _value(existing, "id", 0)),
                )
            else:
                conn.execute(
                    """INSERT INTO classroom_submissions
                       (assignment_id, student_id, content, status, grade, submitted_at)
                       VALUES (?, ?, ?, 'graded', ?, ?)""",
                    (assignment_id, student_id, "Imported score", score, now),
                )
        conn.commit()
        flash(f"Imported {len(records)} student scores successfully.", "success")
        return redirect(url_for("classwork_submissions.supervisor_submissions", class_id=class_id, assignment_id=assignment_id))
    except ValueError as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        flash(str(exc), "danger")
        return redirect(url_for("classwork_scores.import_scores", class_id=class_id, assignment_id=assignment_id))
    finally:
        conn.close()
