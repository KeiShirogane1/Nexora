import shutil
from pathlib import Path

from flask import Blueprint, current_app, jsonify, redirect, request, session, url_for

from app.Http.Middleware.security import login_required
from app.Models.db import get_db_connection
from app.Services.messaging_schema import ensure_messaging_schema
from app.Services.messaging_service import (
    get_authorized_contact,
    get_authorized_contacts,
    get_thread,
    send_message,
)

messages = Blueprint("messages", __name__)


@messages.record_once
def _ensure_schema(_state):
    ensure_messaging_schema()


def _user_profile_picture(user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return ""

    conn = get_db_connection()
    try:
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


def _avatar_file_extension(path):
    """Return the real supported image extension from the file signature."""
    try:
        with path.open("rb") as image_file:
            header = image_file.read(12)
    except OSError:
        return ""

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return ""


def _chat_avatar_filename(filename):
    """Return a browser-safe avatar filename for legacy/missing Render uploads."""
    filename = str(filename or "").strip()
    if not filename or Path(filename).name != filename:
        return ""

    upload_folder = current_app.config.get("PROFILE_UPLOAD_FOLDER")
    if not upload_folder:
        return ""

    source = Path(upload_folder) / filename
    if not source.is_file():
        return ""

    actual_ext = _avatar_file_extension(source)
    if not actual_ext:
        return filename

    current_ext = source.suffix.lower().lstrip(".")
    if current_ext == actual_ext or (actual_ext == "jpg" and current_ext == "jpeg"):
        return filename

    # Older Supervisor uploads were always named .jpg even when the uploaded
    # bytes were PNG/GIF. With X-Content-Type-Options: nosniff, Render browsers
    # can reject those responses. Keep the original file intact and create a
    # correctly named copy on the persistent uploads disk for chat rendering.
    corrected_name = f"{source.stem}.{actual_ext}"
    corrected = source.with_name(corrected_name)
    try:
        if not corrected.is_file():
            shutil.copyfile(source, corrected)
    except OSError:
        return ""
    return corrected_name


def _contact_payload(contact):
    payload = dict(contact or {})
    profile_picture = str(payload.pop("profile_picture", "") or "").strip()

    # Student photos normally come from student_profiles. Supervisor uploads and
    # generic/Admin profile photos are stored on users.profile_picture, so use
    # that canonical account-level value whenever the role-specific lookup is empty.
    if not profile_picture:
        profile_picture = _user_profile_picture(payload.get("id"))

    profile_picture = _chat_avatar_filename(profile_picture)
    if profile_picture:
        payload["avatar_url"] = url_for("profile_picture", filename=profile_picture)
    else:
        payload["avatar_url"] = url_for("static", filename="images/default_profile.png")
    return payload


@messages.route("/messages/contacts")
@login_required
def contacts():
    target_role = (request.args.get("role") or "").strip().lower() or None
    if target_role and target_role not in {"student", "supervisor", "admin"}:
        return jsonify({"ok": False, "error": "Invalid contact role."}), 400

    contacts_data = get_authorized_contacts(
        session.get("user_id"),
        target_role=target_role,
    )
    return jsonify(
        {
            "ok": True,
            "contacts": [_contact_payload(contact) for contact in contacts_data],
        }
    )


@messages.route("/messages/thread/<int:contact_id>")
@login_required
def thread(contact_id):
    data = get_thread(session.get("user_id"), contact_id)
    if not data:
        return jsonify({"ok": False, "error": "Contact not found or unauthorized."}), 403

    payload = dict(data)
    payload["contact"] = _contact_payload(data.get("contact"))
    return jsonify({"ok": True, **payload})


@messages.route("/messages/send", methods=["POST"])
@login_required
def send():
    data = request.get_json(silent=True) or {}
    recipient_id = data.get("recipient_id")
    body = data.get("body")

    try:
        recipient_id = int(recipient_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "A valid recipient is required."}), 400

    try:
        message = send_message(session.get("user_id"), recipient_id, body)
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "message": message}), 201


@messages.route("/messages/open/<int:contact_id>")
@login_required
def open_thread(contact_id):
    if not get_authorized_contact(session.get("user_id"), contact_id):
        return "Message contact not found or unauthorized.", 403

    role = session.get("role")
    endpoint = {
        "student": "student.student_dashboard",
        "supervisor": "supervisor.supervisor_dashboard",
        "admin": "admin.admin_dashboard",
    }.get(role)
    if not endpoint:
        return "Unsupported account role.", 403

    return redirect(url_for(endpoint, assistant="messages", contact=contact_id))
