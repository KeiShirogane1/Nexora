from flask import Blueprint, render_template

from app.Http.Middleware.security import role_required
from app.Services.admin_assigned_interns_service import get_admin_assigned_interns


admin_assigned_interns = Blueprint("admin_assigned_interns", __name__)


@admin_assigned_interns.route("/admin/assigned-interns")
@role_required("admin")
def assigned_interns():
    context = get_admin_assigned_interns()
    return render_template(
        "admin/assigned_interns.html",
        interns=context["interns"],
        supervisors=context["supervisors"],
        summary=context["summary"],
        active_page="assigned_interns",
    )
