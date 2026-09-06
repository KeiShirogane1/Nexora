from flask import Blueprint, session, jsonify, request, render_template
from app.Http.Middleware.security import login_required
from app.Services.notification_service import get_user_notifications, get_unread_count, mark_notification_read, mark_all_read
from app.Models.db import get_db_connection

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/notifications")
@login_required
def notification_list():
    user_id = session.get("user_id")
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,))
    total_count = cursor.fetchone()[0]
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    
    conn.close()
    
    notifications = get_user_notifications(user_id, limit=per_page, offset=offset)
    unread_count = get_unread_count(user_id)
    return render_template("notifications/index.html", notifications=notifications, unread_count=unread_count, active_page="notifications", page=page, total_pages=total_pages, total_count=total_count)


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
