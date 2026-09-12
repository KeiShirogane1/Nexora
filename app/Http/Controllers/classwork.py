import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection, using_postgres
from app.Services.notification_service import create_notification

classwork = Blueprint("classwork", __name__)

ACTIVITY_TYPES = {
    "assignment": "Task",
    "google_form": "Form / Assessment",
    "google_doc": "Online Work",
    "file_reference": "Resource",
    "project": "Project",
    "group_project": "Team Task",
}

ALLOWED_RESOURCE_EXT = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt",
    "png", "jpg", "jpeg", "gif", "zip"
}
MAX_RESOURCE_SIZE = 5 * 1024 * 1024


def _is_owner(supervisor_id, class_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT supervisor_id FROM classrooms WHERE id = ?",
            (class_id,),
        ).fetchone()
        if not row:
            return False
        owner_id = row["supervisor_id"] if "supervisor_id" in row.keys() else row[0]
        return int(owner_id) == int(supervisor_id)
    finally:
        conn.close()


def _student_has_assignment_access(conn, assignment_id, student_id):
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


@classwork.before_app_request
def _protect_legacy_student_assignment_routes():
    if request.endpoint not in {
        "classroom.student_assignment_detail",
        "classroom.student_submit_assignment",
    }:
        return None

    student_id = session.get("user_id")
    assignment_id = (request.view_args or {}).get("assignment_id")
    if not student_id or assignment_id is None:
        return None

    conn = get_db_connection()
    try:
        if not _student_has_assignment_access(conn, assignment_id, student_id):
            abort(403)
    finally:
        conn.close()
    return None


def _valid_external_url(value):
    if not value:
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _resource_filename_allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_RESOURCE_EXT


def _save_resource(upload, class_id, assignment_id):
    if not upload or not upload.filename:
        return None, None

    filename = secure_filename(upload.filename)
    if not filename or not _resource_filename_allowed(filename):
        raise ValueError("Unsupported file type. Please upload a PDF, document, spreadsheet, presentation, image, TXT, or ZIP file.")

    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > MAX_RESOURCE_SIZE:
        raise ValueError("Resource file must be 5 MB or smaller.")

    token = secrets.token_hex(8)
    stored_name = f"{token}_{filename}"
    relative_dir = Path("classwork") / str(class_id) / str(assignment_id)
    absolute_dir = Path(current_app.config["UPLOAD_FOLDER"]) / relative_dir
    absolute_dir.mkdir(parents=True, exist_ok=True)
    absolute_path = absolute_dir / stored_name
    upload.save(str(absolute_path))

    relative_path = str(relative_dir / stored_name).replace(os.sep, "/")
    return filename, relative_path


@classwork.route("/supervisor/classes/<int:class_id>/classwork", methods=["GET", "POST"])
@role_required("supervisor")
def manage_classwork(class_id):
    sid = session["user_id"]
    if not _is_owner(sid, class_id):
        return "Forbidden", 403

    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """SELECT c.id, c.name, c.section, c.description, c.code, c.archived,
                      COALESCE(cid.company_name, '') AS company_name
               FROM classrooms c
               LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
               WHERE c.id = ?""",
            (class_id,),
        ).fetchone()
        if not classroom:
            return "Class not found", 404

        enrolled_rows = conn.execute(
            """SELECT u.id, u.username, u.email
               FROM classroom_students cs
               JOIN users u ON u.id = cs.student_id
               WHERE cs.classroom_id = ?
               ORDER BY LOWER(u.username), LOWER(u.email), u.id""",
            (class_id,),
        ).fetchall()
        enrolled_students = []
        enrolled_ids = set()
        for row in enrolled_rows:
            student_id = row["id"] if "id" in row.keys() else row[0]
            try:
                student_id = int(student_id)
            except (TypeError, ValueError):
                continue
            enrolled_ids.add(student_id)
            enrolled_students.append({
                "id": student_id,
                "username": row["username"] if "username" in row.keys() else row[1],
                "email": row["email"] if "email" in row.keys() else row[2],
            })

        if request.method == "POST":
            if classroom["archived"] if "archived" in classroom.keys() else classroom[5]:
                flash("Archived Intern Classrooms cannot receive new work.", "warning")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))

            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            activity_type = (request.form.get("activity_type") or "assignment").strip()
            due_at = (request.form.get("due_at") or "").strip() or None
            points_raw = (request.form.get("points") or "100").strip()
            external_url = (request.form.get("external_url") or "").strip() or None
            resource_label = (request.form.get("resource_label") or "").strip() or None
            allow_file_upload = 1 if request.form.get("allow_file_upload") == "on" else 0
            group_mode = 1 if request.form.get("group_mode") == "on" else 0
            max_group_size_raw = (request.form.get("max_group_size") or "1").strip()
            assignment_scope = (request.form.get("assignment_scope") or "classroom").strip().lower()
            team_name = (request.form.get("team_name") or "").strip()
            submission_mode = (request.form.get("submission_mode") or "individual").strip().lower()

            if activity_type not in ACTIVITY_TYPES:
                flash("Choose a valid work type.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))
            if assignment_scope not in {"classroom", "selected"}:
                flash("Choose who should receive this work.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))
            if submission_mode not in {"individual", "shared"}:
                flash("Choose a valid submission mode.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))
            if len(title) < 3 or len(title) > 200:
                flash("Title is required and must be 3-200 characters.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))
            if len(description) > 5000:
                flash("Instructions must be 5000 characters or fewer.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))
            if external_url and not _valid_external_url(external_url):
                flash("Resource link must be a valid http:// or https:// URL.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))
            if len(team_name) > 100:
                flash("Team name must be 100 characters or fewer.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))

            selected_recipient_ids = []
            if assignment_scope == "selected":
                seen = set()
                for raw_id in request.form.getlist("recipient_ids"):
                    try:
                        student_id = int(raw_id)
                    except (TypeError, ValueError):
                        flash("One or more selected interns are invalid.", "danger")
                        return redirect(url_for("classwork.manage_classwork", class_id=class_id))
                    if student_id not in enrolled_ids:
                        flash("Work can only be assigned to interns enrolled in this Intern Classroom.", "danger")
                        return redirect(url_for("classwork.manage_classwork", class_id=class_id))
                    if student_id not in seen:
                        seen.add(student_id)
                        selected_recipient_ids.append(student_id)
                if not selected_recipient_ids:
                    flash("Select at least one intern for targeted work.", "danger")
                    return redirect(url_for("classwork.manage_classwork", class_id=class_id))

            if activity_type == "group_project":
                if assignment_scope != "selected":
                    flash("Team Tasks must be assigned to selected interns.", "danger")
                    return redirect(url_for("classwork.manage_classwork", class_id=class_id))
                if len(selected_recipient_ids) < 2:
                    flash("Select at least two interns for a Team Task.", "danger")
                    return redirect(url_for("classwork.manage_classwork", class_id=class_id))
                group_mode = 1
                max_group_size_raw = str(len(selected_recipient_ids))
                team_name = team_name or None
            else:
                team_name = None
                submission_mode = "individual"

            try:
                points = int(points_raw)
                if points < 0 or points > 10000:
                    raise ValueError
            except ValueError:
                flash("Points must be between 0 and 10000.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))

            try:
                max_group_size = int(max_group_size_raw)
                if max_group_size < 1 or max_group_size > 100:
                    raise ValueError
            except ValueError:
                flash("Maximum group size must be between 1 and 100.", "danger")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))

            upload = request.files.get("resource_file")
            resource_filename = None
            resource_filepath = None

            try:
                insert_sql = """INSERT INTO classroom_assignments
                       (classroom_id, author_id, title, description, due_at, points)
                       VALUES (?, ?, ?, ?, ?, ?)"""
                if using_postgres():
                    insert_sql += " RETURNING id"

                insert_cursor = conn.execute(
                    insert_sql,
                    (class_id, sid, title, description, due_at, points),
                )

                if using_postgres():
                    assignment_row = insert_cursor.fetchone()
                    assignment_id = (
                        assignment_row["id"]
                        if assignment_row and "id" in assignment_row.keys()
                        else assignment_row[0] if assignment_row else None
                    )
                else:
                    assignment_id = insert_cursor.lastrowid

                if not assignment_id:
                    raise RuntimeError("Could not determine the new work ID.")

                resource_filename, resource_filepath = _save_resource(upload, class_id, assignment_id)

                conn.execute(
                    """INSERT INTO classroom_assignment_meta
                       (assignment_id, activity_type, external_url, resource_label,
                        resource_filename, resource_filepath, allow_file_upload,
                        group_mode, max_group_size, team_name, submission_mode)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        assignment_id,
                        activity_type,
                        external_url,
                        resource_label,
                        resource_filename,
                        resource_filepath,
                        allow_file_upload,
                        group_mode,
                        max_group_size,
                        team_name,
                        submission_mode,
                    ),
                )

                for student_id in selected_recipient_ids:
                    conn.execute(
                        """INSERT INTO classroom_assignment_recipients
                           (assignment_id, student_id) VALUES (?, ?)""",
                        (assignment_id, student_id),
                    )

                conn.commit()

                try:
                    notification_ids = selected_recipient_ids if assignment_scope == "selected" else [
                        student["id"] for student in enrolled_students
                    ]
                    notification_title = "New Team Task" if activity_type == "group_project" else "New Work"
                    notification_message = (
                        f"{team_name + ': ' if team_name else ''}Team task assigned: {title}"
                        if activity_type == "group_project"
                        else f"New {ACTIVITY_TYPES[activity_type].lower()}: {title}"
                    )
                    for student_id in notification_ids:
                        create_notification(
                            int(student_id),
                            notification_title,
                            notification_message,
                            "classroom",
                            link_url=url_for(
                                "student_classwork.detail",
                                class_id=class_id,
                                assignment_id=assignment_id,
                            ),
                        )
                except Exception as notify_error:
                    print("work notification failed:", notify_error)

                flash("Work created successfully.", "success")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))
            except Exception as error:
                try:
                    conn.rollback()
                except Exception:
                    pass
                flash(f"Unable to create work: {error}", "danger")

        assignments = conn.execute(
            """SELECT a.id, a.title, a.description, a.due_at, a.points, a.created_at,
                      m.activity_type, m.external_url, m.resource_label,
                      m.resource_filename, m.resource_filepath,
                      m.allow_file_upload, m.group_mode, m.max_group_size, m.team_name,
                      COALESCE(m.submission_mode, 'individual') AS submission_mode,
                      (SELECT COUNT(*) FROM classroom_assignment_recipients ar
                       WHERE ar.assignment_id = a.id) AS recipient_count
               FROM classroom_assignments a
               LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
               WHERE a.classroom_id = ?
               ORDER BY a.created_at DESC""",
            (class_id,),
        ).fetchall()

        items = []
        for row in assignments:
            get = lambda key, index: row[key] if key in row.keys() else row[index]
            items.append({
                "id": get("id", 0),
                "title": get("title", 1),
                "description": get("description", 2),
                "due_at": get("due_at", 3),
                "points": get("points", 4),
                "created_at": get("created_at", 5),
                "activity_type": get("activity_type", 6) or "assignment",
                "external_url": get("external_url", 7),
                "resource_label": get("resource_label", 8),
                "resource_filename": get("resource_filename", 9),
                "resource_filepath": get("resource_filepath", 10),
                "allow_file_upload": get("allow_file_upload", 11) or 0,
                "group_mode": get("group_mode", 12) or 0,
                "max_group_size": get("max_group_size", 13) or 1,
                "team_name": get("team_name", 14) or "",
                "submission_mode": get("submission_mode", 15) or "individual",
                "recipient_count": get("recipient_count", 16) or 0,
            })

        classroom_data = {
            "id": classroom["id"] if "id" in classroom.keys() else classroom[0],
            "name": classroom["name"] if "name" in classroom.keys() else classroom[1],
            "section": classroom["section"] if "section" in classroom.keys() else classroom[2],
            "description": classroom["description"] if "description" in classroom.keys() else classroom[3],
            "code": classroom["code"] if "code" in classroom.keys() else classroom[4],
            "archived": classroom["archived"] if "archived" in classroom.keys() else classroom[5],
            "company_name": classroom["company_name"] if "company_name" in classroom.keys() else classroom[6],
        }
    finally:
        conn.close()

    return render_template(
        "classroom/supervisor_classwork.html",
        classroom=classroom_data,
        assignments=items,
        activity_types=ACTIVITY_TYPES,
        enrolled_students=enrolled_students,
        active_page="classes",
    )