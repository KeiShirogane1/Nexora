from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from app.Http.Controllers.classroom import _generate_code
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection


internship_classroom = Blueprint("internship_classroom", __name__)

_SCHEDULE_TYPES = {"fixed_dates", "flexible", "not_specified"}
_HOURS_MODES = {"specified", "not_specified"}
_WORK_ARRANGEMENTS = {"On-site", "Hybrid", "Remote"}


def _valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def _render_form(errors, responsibilities, qualifications):
    return render_template(
        "classroom/create_class.html",
        errors=errors,
        form=request.form,
        responsibilities=responsibilities or [""],
        qualifications=qualifications or [""],
        initial_view="internship",
        active_page="classes",
    )


@internship_classroom.route("/supervisor/classes/create/internship", methods=["POST"])
@role_required("supervisor")
def create_internship_classroom():
    internship_title = (request.form.get("internship_title") or "").strip()
    company_name = (request.form.get("company_name") or "").strip()
    section = (request.form.get("internship_section") or "").strip()
    industry = (request.form.get("industry") or "").strip()
    work_arrangement = (request.form.get("work_arrangement") or "On-site").strip()
    location = (request.form.get("location") or "").strip()
    schedule_type = (request.form.get("schedule_type") or "fixed_dates").strip().lower()
    hours_mode = (request.form.get("hours_mode") or "specified").strip().lower()
    start_date = (request.form.get("start_date") or "").strip() or None
    end_date = (request.form.get("end_date") or "").strip() or None
    deadline = (request.form.get("deadline") or "").strip() or None
    required_hours_raw = (request.form.get("required_hours") or "").strip()
    company_website = (request.form.get("company_website") or "").strip()
    company_description = (request.form.get("company_description") or "").strip()
    internship_description = (request.form.get("internship_description") or "").strip()
    responsibilities = [
        item.strip() for item in request.form.getlist("responsibilities[]") if item.strip()
    ]
    qualifications = [
        item.strip() for item in request.form.getlist("qualifications[]") if item.strip()
    ]

    errors = {}
    if not internship_title or len(internship_title) < 3 or len(internship_title) > 150:
        errors["internship_title"] = "Internship title is required (3-150 chars)."
    if not company_name or len(company_name) < 2 or len(company_name) > 150:
        errors["company_name"] = "Company / organization is required (2-150 chars)."
    if not section or len(section) > 100:
        errors["internship_section"] = "Section is required (1-100 chars)."
    if len(industry) > 100:
        errors["industry"] = "Category / industry max 100 chars."
    if work_arrangement not in _WORK_ARRANGEMENTS:
        errors["work_arrangement"] = "Choose a valid work arrangement."
    if len(location) > 200:
        errors["location"] = "Location max 200 chars."

    if schedule_type not in _SCHEDULE_TYPES:
        errors["schedule_type"] = "Choose a valid schedule option."
    elif schedule_type == "not_specified":
        start_date = None
        end_date = None
    else:
        if schedule_type == "fixed_dates":
            if not start_date:
                errors["start_date"] = "Start date is required for a fixed schedule."
            if not end_date:
                errors["end_date"] = "End date is required for a fixed schedule."
        for field_name, value in (("start_date", start_date), ("end_date", end_date)):
            if value and not _valid_date(value):
                errors[field_name] = "Enter a valid date."
        if start_date and end_date and _valid_date(start_date) and _valid_date(end_date):
            if datetime.strptime(end_date, "%Y-%m-%d") < datetime.strptime(start_date, "%Y-%m-%d"):
                errors["end_date"] = "End date cannot be before the start date."

    if deadline and not _valid_date(deadline):
        errors["deadline"] = "Enter a valid date."

    required_hours = 0
    if hours_mode not in _HOURS_MODES:
        errors["hours_mode"] = "Choose a valid OJT hours option."
    elif hours_mode == "specified":
        try:
            required_hours = int(required_hours_raw)
            if required_hours < 1 or required_hours > 10000:
                raise ValueError()
        except (TypeError, ValueError):
            errors["required_hours"] = "Required hours must be between 1 and 10,000."

    if company_website:
        if len(company_website) > 500:
            errors["company_website"] = "Company website max 500 chars."
        elif not company_website.lower().startswith(("http://", "https://")):
            errors["company_website"] = "Company website must start with http:// or https://."
    if len(company_description) > 5000:
        errors["company_description"] = "Company description max 5000 chars."
    if not internship_description or len(internship_description) < 10 or len(internship_description) > 10000:
        errors["internship_description"] = "Internship description is required (10-10,000 chars)."
    if not responsibilities:
        errors["responsibilities"] = "Add at least one responsibility."
    elif len(responsibilities) > 20 or any(len(item) > 500 for item in responsibilities):
        errors["responsibilities"] = "Use up to 20 responsibilities, max 500 chars each."
    if not qualifications:
        errors["qualifications"] = "Add at least one qualification."
    elif len(qualifications) > 20 or any(len(item) > 500 for item in qualifications):
        errors["qualifications"] = "Use up to 20 qualifications, max 500 chars each."

    if errors:
        return _render_form(errors, responsibilities, qualifications)

    conn = get_db_connection()
    cursor = None
    try:
        cursor = conn.cursor()
        code = _generate_code(cursor)
        parent_description = f"Internship classroom for {company_name}"
        cursor.execute(
            """
            INSERT INTO classrooms
            (supervisor_id, name, section, description, code, classroom_type, archived)
            VALUES (?, ?, ?, ?, ?, 'internship', 0)
            """,
            (session["user_id"], internship_title, section, parent_description, code),
        )
        cursor.execute("SELECT id FROM classrooms WHERE code = ?", (code,))
        classroom_row = cursor.fetchone()
        if not classroom_row:
            raise RuntimeError("Failed to resolve newly created classroom.")
        try:
            classroom_id = classroom_row["id"]
        except Exception:
            classroom_id = classroom_row[0]

        cursor.execute(
            """
            INSERT INTO classroom_internship_details (
                classroom_id, internship_title, company_name, industry,
                work_arrangement, schedule_type, hours_mode, compensation,
                location, start_date, end_date, enrollment_deadline,
                required_hours, company_website, company_description,
                internship_description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                classroom_id,
                internship_title,
                company_name,
                industry or None,
                work_arrangement,
                schedule_type,
                hours_mode,
                "Not Specified",
                location or None,
                start_date,
                end_date,
                deadline,
                required_hours,
                company_website or None,
                company_description or None,
                internship_description,
            ),
        )

        for sort_order, item in enumerate(responsibilities):
            cursor.execute(
                "INSERT INTO classroom_internship_responsibilities (classroom_id, responsibility, sort_order) VALUES (?, ?, ?)",
                (classroom_id, item, sort_order),
            )
        for sort_order, item in enumerate(qualifications):
            cursor.execute(
                "INSERT INTO classroom_internship_qualifications (classroom_id, qualification, sort_order) VALUES (?, ?, ?)",
                (classroom_id, item, sort_order),
            )

        conn.commit()
        flash(
            f"Internship Classroom '{internship_title}' created with code {code}.",
            "success",
        )
        return redirect(url_for("classroom.supervisor_classes"))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Failed to create internship classroom")
        flash("Failed to create internship classroom. Please try again.", "danger")
        return _render_form({}, responsibilities, qualifications)
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        conn.close()
