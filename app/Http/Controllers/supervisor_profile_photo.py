import os
import re
from uuid import uuid4
from flask import Blueprint, current_app, jsonify, request, session, redirect, render_template, flash, url_for
from werkzeug.utils import secure_filename
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.supervisor_profile_service import get_or_create_supervisor_profile
from app.Services.profile_image_storage import (
    ProfileImageStorageError,
    ensure_profile_picture_local,
    mirror_profile_picture,
)

supervisor_profile_photo = Blueprint("supervisor_profile_photo", __name__)


def _row_to_dict(row):
    if not row:
        return {}
    if hasattr(row, "items"):
        return dict(row.items())
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return {}


def _stored_profile_picture(user_id, role):
    if user_id is None:
        return ""
    conn = get_db_connection()
    try:
        if role == "student":
            row = conn.execute(
                "SELECT profile_picture FROM student_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT profile_picture FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
    except Exception:
        row = None
    finally:
        conn.close()

    if not row:
        return ""
    try:
        value = row["profile_picture"]
    except Exception:
        value = row[0] if len(row) else None
    return str(value or "").strip()


@supervisor_profile_photo.before_app_request
def _restore_profile_picture_cache():
    """Restore Cloudinary-backed avatars before existing file routes serve them."""
    upload_folder = current_app.config.get("PROFILE_UPLOAD_FOLDER")
    if not upload_folder:
        return None

    filename = ""
    path = request.path or ""
    profile_prefix = "/uploads/profile_pictures/"
    if path.startswith(profile_prefix):
        filename = path[len(profile_prefix):].strip()
    elif path.startswith("/profile-picture/"):
        try:
            target_user_id = int(path.rstrip("/").rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            target_user_id = None
        if target_user_id is not None:
            filename = _stored_profile_picture(target_user_id, "student")

    if filename:
        ensure_profile_picture_local(filename, upload_folder)
    return None


@supervisor_profile_photo.after_app_request
def _persist_profile_picture_upload(response):
    """Mirror successful Student/Supervisor profile uploads to Cloudinary."""
    if request.method != "POST" or response.status_code >= 400:
        return response

    path = request.path.rstrip("/")
    supported_paths = {
        "/student/profile/setup",
        "/student/profile/photo",
        "/supervisor/profile/photo",
    }
    if path not in supported_paths:
        return response
    if path == "/student/profile/setup" and not request.form.get("cropped_image"):
        return response

    user_id = session.get("user_id")
    role = (session.get("role") or "").strip().lower()
    if user_id is None or role not in {"student", "supervisor", "admin"}:
        return response

    filename = _stored_profile_picture(user_id, role)
    upload_folder = current_app.config.get("PROFILE_UPLOAD_FOLDER")
    if not filename or not upload_folder:
        return response

    try:
        mirror_profile_picture(filename, upload_folder)
    except ProfileImageStorageError:
        current_app.logger.exception(
            "Unable to persist profile picture in Cloudinary for user %s",
            user_id,
        )
    return response


def _profile_payload(form):
    return {
        "first_name": (form.get("first_name") or "").strip(),
        "middle_name": (form.get("middle_name") or "").strip(),
        "last_name": (form.get("last_name") or "").strip(),
        "employee_id": (form.get("employee_id") or "").strip(),
        "job_title": (form.get("job_title") or "").strip(),
        "department": (form.get("department") or "").strip(),
        "specialization": (form.get("specialization") or "").strip(),
        "years_experience": (form.get("years_experience") or "0").strip(),
        "education": (form.get("education") or "").strip(),
        "certifications": (form.get("certifications") or "").strip(),
        "phone_number": (form.get("phone_number") or "").strip(),
        "office_location": (form.get("office_location") or "").strip(),
        "office_hours": (form.get("office_hours") or "").strip(),
        "preferred_contact": (form.get("preferred_contact") or "").strip(),
        "response_time": (form.get("response_time") or "").strip(),
        "availability": (form.get("availability") or "").strip(),
        "skills": (form.get("skills") or "").strip(),
        "bio": (form.get("bio") or "").strip(),
    }


def _profile_is_complete(profile):
    data = _row_to_dict(profile)
    if not data:
        return False
    return all(
        str(data.get(field) or "").strip()
        for field in ("first_name", "last_name", "job_title", "department")
    )


def _setup_payload(form):
    return {
        "first_name": (form.get("first_name") or "").strip(),
        "middle_name": (form.get("middle_name") or "").strip(),
        "last_name": (form.get("last_name") or "").strip(),
        "job_title": (form.get("job_title") or "").strip(),
        "department": (form.get("department") or "").strip(),
        "employee_id": (form.get("employee_id") or "").strip(),
        "specialization": (form.get("specialization") or "").strip(),
        "years_experience": (form.get("years_experience") or "0").strip(),
        "phone_number": (form.get("phone_number") or "").strip(),
        "office_location": (form.get("office_location") or "").strip(),
        "office_hours": (form.get("office_hours") or "").strip(),
    }


def _setup_errors(payload):
    errors = {}
    required_limits = {
        "first_name": ("First name is required.", 80),
        "last_name": ("Last name is required.", 80),
        "job_title": ("Position/title is required.", 120),
        "department": ("Department is required.", 120),
    }
    for field, (message, limit) in required_limits.items():
        if not payload[field]:
            errors[field] = message
        elif len(payload[field]) > limit:
            errors[field] = f"Must be {limit} characters or fewer."

    optional_limits = {
        "middle_name": 80,
        "employee_id": 80,
        "specialization": 180,
        "phone_number": 40,
        "office_location": 180,
        "office_hours": 180,
    }
    for field, limit in optional_limits.items():
        if payload[field] and len(payload[field]) > limit:
            errors[field] = f"Must be {limit} characters or fewer."

    try:
        years = int(payload["years_experience"] or 0)
        if years < 0 or years > 60:
            raise ValueError
        payload["years_experience"] = years
    except (TypeError, ValueError):
        errors["years_experience"] = "Years of experience must be a whole number from 0 to 60."
        payload["years_experience"] = 0

    return errors


def _render_supervisor_setup(user_id, profile_data=None, errors=None):
    if profile_data is None:
        profile = get_or_create_supervisor_profile(user_id)
        profile_data = _row_to_dict(profile)
    return render_template(
        "supervisor/profile_setup.html",
        profile=profile_data,
        errors=errors or {},
    )


def _profile_stats(user_id):
    conn = get_db_connection()
    try:
        class_count = conn.execute("SELECT COUNT(*) FROM classrooms WHERE supervisor_id = ? AND archived = 0", (user_id,)).fetchone()[0]
        intern_count = conn.execute("SELECT COUNT(DISTINCT student_id) FROM classroom_students cs JOIN classrooms c ON c.id = cs.classroom_id WHERE c.supervisor_id = ? AND c.archived = 0", (user_id,)).fetchone()[0]
        assignment_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE supervisor_id = ?", (user_id,)).fetchone()[0]
        feedback_count = conn.execute("SELECT COUNT(*) FROM feedback WHERE supervisor_id = ?", (user_id,)).fetchone()[0]
        return {"class_count": class_count, "intern_count": intern_count, "assignment_count": assignment_count, "feedback_count": feedback_count}
    finally:
        conn.close()


def _render_supervisor_profile(user_id, errors=None):
    conn = get_db_connection()
    try:
        user = conn.execute("SELECT id, username, email, role, status, profile_picture FROM users WHERE id = ? AND role = 'supervisor'", (user_id,)).fetchone()
    finally:
        conn.close()
    if not user:
        return redirect(url_for("auth.login"))
    profile = get_or_create_supervisor_profile(user_id)
    profile_data = _row_to_dict(profile)
    user_data = _row_to_dict(user)
    return render_template("supervisor/profile.html", supervisor=user_data, profile=profile_data, errors=errors or {}, active_page="profile", **_profile_stats(user_id))


@supervisor_profile_photo.before_app_request
def _supervisor_profile_page():
    if session.get("user_id") is not None and session.get("role") == "supervisor":
        if request.path.rstrip("/") == "/supervisor/dashboard":
            profile = get_or_create_supervisor_profile(session["user_id"])
            if not _profile_is_complete(profile):
                return redirect(url_for("supervisor_profile_photo.supervisor_profile_setup"))

    if request.path.rstrip("/") != "/supervisor/profile":
        return None
    if session.get("user_id") is None or session.get("role") != "supervisor":
        return None

    user_id = session["user_id"]
    get_or_create_supervisor_profile(user_id)

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        payload = _profile_payload(request.form)
        errors = {}

        if not username or len(username) < 3 or not re.match(r"^[A-Za-z0-9_.-]+$", username):
            errors["username"] = "Use at least 3 letters, numbers, dots, underscores, or hyphens."
        if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors["email"] = "Enter a valid email address."
        if not payload["first_name"]:
            errors["first_name"] = "First name is required."
        if not payload["last_name"]:
            errors["last_name"] = "Last name is required."
        if not payload["job_title"]:
            errors["job_title"] = "Position/title is required."
        if not payload["department"]:
            errors["department"] = "Department is required."
        try:
            payload["years_experience"] = max(0, min(60, int(payload["years_experience"] or 0)))
        except ValueError:
            errors["years_experience"] = "Years of experience must be a whole number."
            payload["years_experience"] = 0
        if len(payload["bio"]) > 1500:
            errors["bio"] = "About Me must be 1500 characters or fewer."
        if len(payload["skills"]) > 500:
            errors["skills"] = "Skills must be 500 characters or fewer."
        if payload["employee_id"] and len(payload["employee_id"]) > 80:
            errors["employee_id"] = "Employee ID is too long."

        conn = get_db_connection()
        try:
            if not errors:
                duplicate = conn.execute("SELECT id FROM users WHERE username = ? AND id != ?", (username, user_id)).fetchone()
                if duplicate:
                    errors["username"] = "Username already exists."
                duplicate = conn.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(?) AND id != ?", (email, user_id)).fetchone()
                if duplicate:
                    errors["email"] = "Email already exists."
                if payload["employee_id"]:
                    duplicate = conn.execute("SELECT id FROM supervisor_profiles WHERE employee_id = ? AND user_id != ?", (payload["employee_id"], user_id)).fetchone()
                    if duplicate:
                        errors["employee_id"] = "Employee ID already exists."

            if errors:
                user = conn.execute("SELECT id, username, email, role, status, profile_picture FROM users WHERE id = ?", (user_id,)).fetchone()
                profile = conn.execute("SELECT * FROM supervisor_profiles WHERE user_id = ?", (user_id,)).fetchone()
                user_data = _row_to_dict(user)
                profile_data = _row_to_dict(profile) or dict(payload)
                for key, value in payload.items():
                    profile_data[key] = value
                return render_template("supervisor/profile.html", supervisor=user_data, profile=profile_data, errors=errors, active_page="profile", **_profile_stats(user_id))

            conn.execute("UPDATE users SET username = ?, email = ? WHERE id = ?", (username, email, user_id))
            conn.execute("""
                UPDATE supervisor_profiles
                SET first_name = ?, middle_name = ?, last_name = ?, employee_id = ?, job_title = ?,
                    department = ?, specialization = ?, years_experience = ?, education = ?,
                    certifications = ?, phone_number = ?, office_location = ?, office_hours = ?,
                    preferred_contact = ?, response_time = ?, availability = ?, skills = ?, bio = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (
                payload["first_name"], payload["middle_name"], payload["last_name"], payload["employee_id"] or None,
                payload["job_title"], payload["department"], payload["specialization"], payload["years_experience"],
                payload["education"], payload["certifications"], payload["phone_number"], payload["office_location"],
                payload["office_hours"], payload["preferred_contact"], payload["response_time"], payload["availability"],
                payload["skills"], payload["bio"], user_id
            ))
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            flash(f"Unable to save profile: {exc}", "danger")
            return _render_supervisor_profile(user_id)
        finally:
            conn.close()

        flash("Supervisor profile updated successfully.", "success")
        return redirect(url_for("supervisor.supervisor_profile"))

    return _render_supervisor_profile(user_id)


@supervisor_profile_photo.route("/supervisor/profile/setup", methods=["GET", "POST"])
@role_required("supervisor")
def supervisor_profile_setup():
    user_id = session["user_id"]
    profile = get_or_create_supervisor_profile(user_id)

    if request.method == "GET" and _profile_is_complete(profile):
        return redirect(url_for("supervisor.supervisor_dashboard"))

    if request.method == "POST":
        payload = _setup_payload(request.form)
        errors = _setup_errors(payload)
        conn = get_db_connection()
        try:
            if payload["employee_id"] and not errors.get("employee_id"):
                duplicate = conn.execute(
                    "SELECT id FROM supervisor_profiles WHERE employee_id = ? AND user_id != ?",
                    (payload["employee_id"], user_id),
                ).fetchone()
                if duplicate:
                    errors["employee_id"] = "Employee ID already exists."

            if errors:
                profile_data = _row_to_dict(profile)
                profile_data.update(payload)
                return _render_supervisor_setup(user_id, profile_data=profile_data, errors=errors)

            conn.execute(
                """
                UPDATE supervisor_profiles
                SET first_name = ?, middle_name = ?, last_name = ?, job_title = ?,
                    department = ?, employee_id = ?, specialization = ?, years_experience = ?,
                    phone_number = ?, office_location = ?, office_hours = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (
                    payload["first_name"],
                    payload["middle_name"],
                    payload["last_name"],
                    payload["job_title"],
                    payload["department"],
                    payload["employee_id"] or None,
                    payload["specialization"],
                    payload["years_experience"],
                    payload["phone_number"],
                    payload["office_location"],
                    payload["office_hours"],
                    user_id,
                ),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            current_app.logger.exception("Unable to complete supervisor profile setup")
            flash("Unable to save your profile right now. Please try again.", "danger")
            return _render_supervisor_setup(user_id)
        finally:
            conn.close()

        flash("Supervisor profile setup complete.", "success")
        return redirect(url_for("supervisor.supervisor_dashboard"))

    return _render_supervisor_setup(user_id)


@supervisor_profile_photo.route("/supervisor/profile/photo", methods=["POST"])
@role_required("supervisor")
def update_photo():
    file = request.files.get("profile_picture")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No image received"}), 400
    name = secure_filename(file.filename)
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in {"png", "jpg", "jpeg", "gif"}:
        return jsonify({"ok": False, "error": "Image type not allowed"}), 400
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > 2 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image too large (max 2MB)"}), 400
    filename = f"supervisor_{session['user_id']}_{uuid4().hex[:10]}.jpg"
    path = os.path.join(current_app.config["PROFILE_UPLOAD_FOLDER"], filename)
    file.save(path)
    conn = get_db_connection()
    try:
        conn.execute("UPDATE users SET profile_picture = ? WHERE id = ? AND role = 'supervisor'", (filename, session["user_id"]))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "url": f"/uploads/profile_pictures/{filename}"})
