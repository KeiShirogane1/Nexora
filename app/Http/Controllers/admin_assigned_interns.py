from flask import Blueprint, jsonify, render_template

from app.Http.Middleware.security import role_required
from app.Services.admin_assigned_interns_service import (
    get_admin_assigned_interns,
    get_admin_student_management_context,
    get_admin_supervisor_management_context,
)


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


@admin_assigned_interns.route("/admin/management-directory/students")
@role_required("admin")
def student_management_context():
    return jsonify(get_admin_student_management_context())


@admin_assigned_interns.route("/admin/management-directory/supervisors")
@role_required("admin")
def supervisor_management_context():
    return jsonify(get_admin_supervisor_management_context())
