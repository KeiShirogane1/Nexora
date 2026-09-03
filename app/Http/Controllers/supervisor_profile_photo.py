import os
import re
from flask import Blueprint, current_app, jsonify, request, session, redirect, render_template, flash, url_for
from werkzeug.utils import secure_filename
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.supervisor_profile_service import get_or_create_supervisor_profile

supervisor_profile_photo = Blueprint("supervisor_profile_photo", __name__)


def _profile_payload(form):
    payload = {
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
    return payload


def _display_name(profile, username):
    parts = [profile.get("first_name"), profile.get("middle_name"), profile.get("last_name")]
    name = " ".join(x for x in parts if x)
    return name or username


def _render_supervisor_profile(user_id, errors=None):
    conn = get_db_connection()
    try:
        user = conn.execute("SELECT id, username, email, role, status, profile_picture FROM users WHERE id = ? AND role = 'supervisor'", (user_id,)).fetchone()
    finally:
        conn.close()
    if not user:
        return redirect(url_for("auth.login"))
    profile = get_or_create_supervisor_profile(user_id)
    profile_data = dict(profile.items()) if hasattr(profile, "items") else {}
    user_data = dict(user.items()) if hasattr(user, "items") else {}
    return render_template("supervisor/profile.html", supervisor=user_data, profile=profile_data, errors=errors or {}, active_page="profile")


@supervisor_profile_photo.before_app_request
def _supervisor_profile_page():
    # Replace the legacy profile handler without changing the large supervisor controller.
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
                user_data = dict(user.items()) if user and hasattr(user, "items") else {}
                profile_data = dict(profile.items()) if profile and hasattr(profile, "items") else payload
                for key, value in payload.items():
                    profile_data[key] = value
                return render_template("supervisor/profile.html", supervisor=user_data, profile=profile_data, errors=errors, active_page="profile")

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
    filename = f"supervisor_{session['user_id']}_profile.jpg"
    path = os.path.join(current_app.config["PROFILE_UPLOAD_FOLDER"], filename)
    file.save(path)
    conn = get_db_connection()
    try:
        conn.execute("UPDATE users SET profile_picture = ? WHERE id = ? AND role = 'supervisor'", (filename, session["user_id"]))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "url": f"/uploads/profile_pictures/{filename}"})
