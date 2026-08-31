from flask import Blueprint, session, jsonify, request
from app.Http.Middleware.security import login_required
from app.Services.notification_service import mark_notification_read, mark_all_read

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/notification/read/<int:notification_id>", methods=["POST"])
@login_required
def read_notification(notification_id):
    user_id = session.get("user_id")
    success = mark_notification_read(notification_id, user_id=user_id)
    if not success:
        return jsonify({"ok": False, "error": "Not found or unauthorized"}), 404
    return jsonify({"ok": True})


@notifications_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def read_all_notifications():
    user_id = session.get("user_id")
    count = mark_all_read(user_id)
    return jsonify({"ok": True, "updated": count})


@notifications_bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def mark_read_json():
    data = request.get_json(silent=True) or {}
    nid = data.get("id") or request.form.get("id")
    if not nid:
        return jsonify({"ok": False, "error": "id required"}), 400
    try:
        nid = int(nid)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid id"}), 400
    user_id = session.get("user_id")
    success = mark_notification_read(nid, user_id=user_id)
    if not success:
        return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True})
