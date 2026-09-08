from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from app.Http.Middleware.security import login_required
from app.Models.db import get_db_connection
from app.Services.notification_service import (
    delete_notifications_by_date,
    get_unread_count,
    get_user_notifications,
    mark_all_read,
    mark_notification_read,
)

notifications_bp = Blueprint("notifications", __name__)

NOTIFICATIONS_PER_PAGE = 15
MAX_NOTIFICATION_PAGES = 499


def _build_pagination_items(page, total_pages):
    visible = {1, total_pages}
    visible.update(range(max(1, page - 2), min(total_pages, page + 2) + 1))
    pages = sorted(visible)

    items = []
    previous = None
    for current in pages:
        if previous is not None and current - previous > 1:
            items.append(None)
        items.append(current)
        previous = current
    return items


@notifications_bp.route("/notifications")
@login_required
def notification_list():
    user_id = session.get("user_id")
    requested_page = request.args.get("page", 1, type=int) or 1

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,))
        total_count = int(cursor.fetchone()[0])
    finally:
        conn.close()

    calculated_pages = max(1, (total_count + NOTIFICATIONS_PER_PAGE - 1) // NOTIFICATIONS_PER_PAGE)
    total_pages = min(MAX_NOTIFICATION_PAGES, calculated_pages)
    page = max(1, min(requested_page, total_pages))
    offset = (page - 1) * NOTIFICATIONS_PER_PAGE

    notifications = get_user_notifications(
        user_id,
        limit=NOTIFICATIONS_PER_PAGE,
        offset=offset,
    )
    unread_count = get_unread_count(user_id)

    page_start = offset + 1 if notifications else 0
    page_end = offset + len(notifications)

    role = session.get("role", "student")
    template_by_role = {
        "student": "notifications/student.html",
        "supervisor": "notifications/supervisor.html",
        "admin": "notifications/admin.html",
    }
    template_name = template_by_role.get(role, "notifications/student.html")

    return render_template(
        template_name,
        notifications=notifications,
        unread_count=unread_count,
        active_page="notifications",
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        page_start=page_start,
        page_end=page_end,
        pagination_items=_build_pagination_items(page, total_pages),
        pagination_capped=calculated_pages > MAX_NOTIFICATION_PAGES,
        today_iso=date.today().isoformat(),
    )


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


@notifications_bp.route("/notifications/delete-by-date", methods=["POST"])
@login_required
def delete_by_date():
    user_id = session.get("user_id")
    raw_date = (request.form.get("delete_date") or "").strip()

    if not raw_date:
        flash("Choose a date before deleting notifications.", "error")
        return redirect(url_for("notifications.notification_list"))

    try:
        target_date = date.fromisoformat(raw_date)
    except ValueError:
        flash("The selected notification date is invalid.", "error")
        return redirect(url_for("notifications.notification_list"))

    if target_date > date.today():
        flash("Choose today or an earlier date.", "error")
        return redirect(url_for("notifications.notification_list"))

    deleted_count = delete_notifications_by_date(user_id, target_date)
    if deleted_count:
        flash(
            f"Permanently deleted {deleted_count} notification{'s' if deleted_count != 1 else ''} from {target_date.strftime('%B %d, %Y')}.",
            "success",
        )
    else:
        flash(
            f"No notifications were found for {target_date.strftime('%B %d, %Y')}.",
            "info",
        )

    return redirect(url_for("notifications.notification_list"))


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
