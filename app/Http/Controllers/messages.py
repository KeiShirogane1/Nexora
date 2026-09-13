from flask import Blueprint, jsonify, redirect, request, session, url_for

from app.Http.Middleware.security import login_required
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


def _contact_payload(contact):
    payload = dict(contact or {})
    profile_picture = str(payload.pop("profile_picture", "") or "").strip()
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
