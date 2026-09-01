import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.notification_service import create_notification

classwork = Blueprint("classwork", __name__)

ACTIVITY_TYPES = {
    "assignment": "Assignment",
    "google_form": "Google Form / Quiz",
    "google_doc": "Google Docs / Sheets",
    "file_reference": "File / Reference Material",
    "project": "Project",
    "group_project": "Group Project",
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
            "SELECT id, name, section, archived FROM classrooms WHERE id = ?",
            (class_id,),
        ).fetchone()
        if not classroom:
            return "Class not found", 404

        if request.method == "POST":
            if classroom["archived"] if "archived" in classroom.keys() else classroom[3]:
                flash("Archived classes cannot receive new classwork.", "warning")
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

            if activity_type not in ACTIVITY_TYPES:
                flash("Choose a valid classwork type.", "danger")
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
                conn.execute(
                    """INSERT INTO classroom_assignments
                       (classroom_id, author_id, title, description, due_at, points)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (class_id, sid, title, description, due_at, points),
                )
                assignment_row = conn.execute(
                    """SELECT MAX(id) AS id
                       FROM classroom_assignments
                       WHERE classroom_id = ? AND author_id = ?""",
                    (class_id, sid),
                ).fetchone()
                assignment_id = assignment_row["id"] if "id" in assignment_row.keys() else assignment_row[0]
                if not assignment_id:
                    raise RuntimeError("Could not determine the new classwork ID.")

                resource_filename, resource_filepath = _save_resource(upload, class_id, assignment_id)

                conn.execute(
                    """INSERT INTO classroom_assignment_meta
                       (assignment_id, activity_type, external_url, resource_label,
                        resource_filename, resource_filepath, allow_file_upload,
                        group_mode, max_group_size)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    ),
                )
                conn.commit()

                try:
                    students = conn.execute(
                        "SELECT student_id FROM classroom_students WHERE classroom_id = ?",
                        (class_id,),
                    ).fetchall()
                    for student in students:
                        student_id = student["student_id"] if "student_id" in student.keys() else student[0]
                        create_notification(
                            int(student_id),
                            "New Classwork",
                            f"New {ACTIVITY_TYPES[activity_type].lower()}: {title}",
                            "classroom",
                            link_url=f"/student/classes/{class_id}/assignments/{assignment_id}",
                        )
                except Exception as notify_error:
                    print("classwork notification failed:", notify_error)

                flash("Classwork created successfully.", "success")
                return redirect(url_for("classwork.manage_classwork", class_id=class_id))
            except Exception as error:
                try:
                    conn.rollback()
                except Exception:
                    pass
                flash(f"Unable to create classwork: {error}", "danger")

        assignments = conn.execute(
            """SELECT a.id, a.title, a.description, a.due_at, a.points, a.created_at,
                      m.activity_type, m.external_url, m.resource_label,
                      m.resource_filename, m.resource_filepath,
                      m.allow_file_upload, m.group_mode, m.max_group_size
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
            })

        classroom_data = {
            "id": classroom["id"] if "id" in classroom.keys() else classroom[0],
            "name": classroom["name"] if "name" in classroom.keys() else classroom[1],
            "section": classroom["section"] if "section" in classroom.keys() else classroom[2],
            "archived": classroom["archived"] if "archived" in classroom.keys() else classroom[3],
        }
    finally:
        conn.close()

    return render_template(
        "classroom/supervisor_classwork.html",
        classroom=classroom_data,
        assignments=items,
        activity_types=ACTIVITY_TYPES,
        active_page="classes",
    )
