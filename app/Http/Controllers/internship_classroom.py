import math
import os
import shutil
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from app.Http.Controllers.classroom import _generate_code
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.internship_schedule_service import (
    DEFAULT_ATTENDANCE_DAYS,
    DEFAULT_END_TIME,
    DEFAULT_HOURS_PER_DAY,
    DEFAULT_START_TIME,
    ensure_internship_schedule_schema,
    ensure_supervisor_completion_notifications,
    get_student_schedule_state,
    normalize_attendance_days,
)


internship_classroom = Blueprint("internship_classroom", __name__)

_WORK_ARRANGEMENTS = {"On-site", "Hybrid", "Remote"}
_BANNER_THEMES = {"blue", "navy", "green", "teal", "purple", "orange", "amber", "rose", "slate"}


def _valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def _valid_time(value):
    try:
        return datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        return None


def _row_value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except AttributeError:
        pass
    try:
        value = row[index]
        return default if value is None else value
    except (IndexError, KeyError, TypeError):
        return default


def _get_classroom_banner_theme(class_id):
    try:
        class_id = int(class_id)
    except (TypeError, ValueError):
        return "blue"

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT banner_theme FROM classrooms WHERE id = ?",
            (class_id,),
        ).fetchone()
        theme = str(_row_value(row, "banner_theme", 0, "blue")).lower()
        return theme if theme in _BANNER_THEMES else "blue"
    except Exception:
        return "blue"
    finally:
        conn.close()


def _get_classroom_internship_details(class_id):
    """Read all stored Intern Classroom information for existing view components."""
    try:
        class_id = int(class_id)
    except (TypeError, ValueError):
        return {}
    try:
        ensure_internship_schedule_schema()
    except Exception:
        return {}

    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT internship_title, program, company_name, industry, work_arrangement,
                   schedule_type, hours_mode, compensation, location, start_date, end_date,
                   enrollment_deadline, required_hours, hours_per_day, required_days,
                   attendance_days, shift_start_time, shift_end_time, company_website,
                   company_description, internship_description
            FROM classroom_internship_details
            WHERE classroom_id = ?
            LIMIT 1
            """,
            (class_id,),
        ).fetchone()
        if not row:
            return {}
        keys = [
            "internship_title", "program", "company_name", "industry", "work_arrangement",
            "schedule_type", "hours_mode", "compensation", "location", "start_date", "end_date",
            "enrollment_deadline", "required_hours", "hours_per_day", "required_days",
            "attendance_days", "shift_start_time", "shift_end_time", "company_website",
            "company_description", "internship_description",
        ]
        details = {key: _row_value(row, key, index, "") for index, key in enumerate(keys)}
        responsibility_rows = conn.execute(
            "SELECT responsibility FROM classroom_internship_responsibilities WHERE classroom_id = ? ORDER BY sort_order, id",
            (class_id,),
        ).fetchall()
        qualification_rows = conn.execute(
            "SELECT qualification FROM classroom_internship_qualifications WHERE classroom_id = ? ORDER BY sort_order, id",
            (class_id,),
        ).fetchall()
        details["responsibilities"] = [
            _row_value(item, "responsibility", 0, "")
            for item in responsibility_rows
            if _row_value(item, "responsibility", 0, "")
        ]
        details["qualifications"] = [
            _row_value(item, "qualification", 0, "")
            for item in qualification_rows
            if _row_value(item, "qualification", 0, "")
        ]
        return details
    finally:
        conn.close()


@internship_classroom.app_context_processor
def inject_internship_helpers():
    return {
        "classroom_banner_theme": _get_classroom_banner_theme,
        "get_student_schedule_state": get_student_schedule_state,
        "get_classroom_internship_details": _get_classroom_internship_details,
    }


@internship_classroom.before_app_request
def notify_supervisor_when_internship_finishes():
    if request.method != "GET" or session.get("role") != "supervisor" or not session.get("user_id"):
        return None
    if request.path.startswith("/static/"):
        return None
    try:
        ensure_supervisor_completion_notifications(session["user_id"])
    except Exception:
        current_app.logger.warning("Intern Classroom completion notification check failed", exc_info=True)
    return None


def _selected_days_from_request():
    selected = normalize_attendance_days(request.form.getlist("attendance_days"))
    return selected or list(DEFAULT_ATTENDANCE_DAYS)


def _render_form(errors, responsibilities, qualifications, selected_days=None):
    return render_template(
        "classroom/create_class.html",
        errors=errors,
        form=request.form,
        responsibilities=responsibilities or [""],
        qualifications=qualifications or [""],
        selected_days=selected_days or _selected_days_from_request(),
        initial_view="internship",
        active_page="classes",
    )


def _render_edit_form(class_id, form, errors, responsibilities, qualifications, selected_days=None):
    return render_template(
        "classroom/edit_intern_class.html",
        class_id=class_id,
        errors=errors,
        form=form,
        responsibilities=responsibilities or [""],
        qualifications=qualifications or [""],
        selected_days=selected_days or list(DEFAULT_ATTENDANCE_DAYS),
        active_page="classes",
    )


def _read_schedule_form(errors):
    program = (request.form.get("program") or "").strip()
    hours_per_day_raw = (request.form.get("hours_per_day") or "").strip()
    required_days_raw = (request.form.get("required_days") or "").strip()
    shift_start_time = (request.form.get("shift_start_time") or DEFAULT_START_TIME).strip()
    shift_end_time = (request.form.get("shift_end_time") or DEFAULT_END_TIME).strip()
    selected_days = _selected_days_from_request()

    if not program or len(program) > 150:
        errors["program"] = "Program is required (1-150 chars)."

    hours_per_day = 0
    try:
        hours_per_day = int(hours_per_day_raw)
        if hours_per_day < 1 or hours_per_day > 24:
            raise ValueError()
    except (TypeError, ValueError):
        errors["hours_per_day"] = "Hours per day must be between 1 and 24."

    required_days = 0
    try:
        required_days = int(required_days_raw)
        if required_days < 1 or required_days > 3650:
            raise ValueError()
    except (TypeError, ValueError):
        errors["required_days"] = "Number of OJT days must be between 1 and 3,650."

    if not selected_days:
        errors["attendance_days"] = "Choose at least one attendance day."

    start_dt = _valid_time(shift_start_time)
    end_dt = _valid_time(shift_end_time)
    if not start_dt:
        errors["shift_start_time"] = "Choose a valid start time."
    if not end_dt:
        errors["shift_end_time"] = "Choose a valid end time."
    if start_dt and end_dt:
        window_hours = (end_dt - start_dt).total_seconds() / 3600
        if window_hours <= 0:
            errors["shift_end_time"] = "End time must be after the start time."
        elif hours_per_day and hours_per_day > window_hours:
            errors["hours_per_day"] = "Hours per day cannot be longer than the daily schedule window."

    required_hours = hours_per_day * required_days if hours_per_day and required_days else 0
    return {
        "program": program,
        "hours_per_day": hours_per_day,
        "required_days": required_days,
        "required_hours": required_hours,
        "attendance_days": selected_days,
        "attendance_days_text": ",".join(selected_days),
        "shift_start_time": shift_start_time,
        "shift_end_time": shift_end_time,
    }


def _validate_common_fields(errors, internship_title, company_name, section, industry, work_arrangement, location, deadline, company_website, company_description, internship_description, responsibilities, qualifications):
    if not internship_title or len(internship_title) < 3 or len(internship_title) > 150:
        errors["internship_title"] = "Intern Classroom name is required (3-150 chars)."
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
    if deadline and not _valid_date(deadline):
        errors["deadline"] = "Enter a valid enrollment deadline."
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


@internship_classroom.route("/supervisor/classes/create/internship", methods=["POST"])
@role_required("supervisor")
def create_internship_classroom():
    ensure_internship_schedule_schema()

    internship_title = (request.form.get("internship_title") or "").strip()
    company_name = (request.form.get("company_name") or "").strip()
    section = (request.form.get("internship_section") or "").strip()
    industry = (request.form.get("industry") or "").strip()
    work_arrangement = (request.form.get("work_arrangement") or "On-site").strip()
    location = (request.form.get("location") or "").strip()
    deadline = (request.form.get("deadline") or "").strip() or None
    company_website = (request.form.get("company_website") or "").strip()
    company_description = (request.form.get("company_description") or "").strip()
    internship_description = (request.form.get("internship_description") or "").strip()
    responsibilities = [item.strip() for item in request.form.getlist("responsibilities[]") if item.strip()]
    qualifications = [item.strip() for item in request.form.getlist("qualifications[]") if item.strip()]

    errors = {}
    _validate_common_fields(
        errors,
        internship_title,
        company_name,
        section,
        industry,
        work_arrangement,
        location,
        deadline,
        company_website,
        company_description,
        internship_description,
        responsibilities,
        qualifications,
    )
    schedule = _read_schedule_form(errors)

    if errors:
        return _render_form(errors, responsibilities, qualifications, schedule["attendance_days"])

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
        classroom_id = _row_value(classroom_row, "id", 0)

        cursor.execute(
            """
            INSERT INTO classroom_internship_details (
                classroom_id, internship_title, program, company_name, industry,
                work_arrangement, schedule_type, hours_mode, compensation,
                location, start_date, end_date, enrollment_deadline,
                hours_per_day, required_days, attendance_days,
                shift_start_time, shift_end_time, required_hours,
                company_website, company_description, internship_description
            ) VALUES (?, ?, ?, ?, ?, ?, 'weekly', 'specified', ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                classroom_id,
                internship_title,
                schedule["program"],
                company_name,
                industry or None,
                work_arrangement,
                "Not Specified",
                location or None,
                deadline,
                schedule["hours_per_day"],
                schedule["required_days"],
                schedule["attendance_days_text"],
                schedule["shift_start_time"],
                schedule["shift_end_time"],
                schedule["required_hours"],
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
        flash(f"Intern Classroom '{internship_title}' created with code {code}.", "success")
        return redirect(url_for("classroom.supervisor_classes"))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Failed to create internship classroom")
        flash("Failed to create internship classroom. Please try again.", "danger")
        return _render_form({}, responsibilities, qualifications, schedule["attendance_days"])
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        conn.close()


@internship_classroom.route("/supervisor/classes/<int:class_id>/edit", methods=["GET", "POST"])
@role_required("supervisor")
def edit_intern_classroom(class_id):
    ensure_internship_schedule_schema()
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            "SELECT id, supervisor_id, name, section, classroom_type FROM classrooms WHERE id = ?",
            (class_id,),
        ).fetchone()
        if not classroom:
            return "Class not found", 404
        if int(_row_value(classroom, "supervisor_id", 1, 0)) != int(supervisor_id):
            return "Forbidden", 403

        details = conn.execute(
            """
            SELECT internship_title, program, company_name, industry, work_arrangement,
                   schedule_type, hours_mode, location, start_date, end_date,
                   enrollment_deadline, required_hours, hours_per_day, required_days,
                   attendance_days, shift_start_time, shift_end_time,
                   company_website, company_description, internship_description
            FROM classroom_internship_details WHERE classroom_id = ?
            """,
            (class_id,),
        ).fetchone()
        if not details:
            flash("This older classroom does not have Intern Classroom details to edit.", "warning")
            return redirect(url_for("classroom.supervisor_class", class_id=class_id))

        if request.method == "GET":
            responsibility_rows = conn.execute(
                "SELECT responsibility FROM classroom_internship_responsibilities WHERE classroom_id = ? ORDER BY sort_order, id",
                (class_id,),
            ).fetchall()
            qualification_rows = conn.execute(
                "SELECT qualification FROM classroom_internship_qualifications WHERE classroom_id = ? ORDER BY sort_order, id",
                (class_id,),
            ).fetchall()

            legacy_required_hours = int(_row_value(details, "required_hours", 11, 0) or 0)
            hours_per_day = int(_row_value(details, "hours_per_day", 12, DEFAULT_HOURS_PER_DAY) or DEFAULT_HOURS_PER_DAY)
            required_days = int(_row_value(details, "required_days", 13, 0) or 0)
            if required_days <= 0 and legacy_required_hours > 0:
                required_days = max(1, int(math.ceil(legacy_required_hours / max(hours_per_day, 1))))

            form = {
                "internship_title": _row_value(details, "internship_title", 0, ""),
                "program": _row_value(details, "program", 1, "") or _row_value(classroom, "section", 3, ""),
                "company_name": _row_value(details, "company_name", 2, ""),
                "internship_section": _row_value(classroom, "section", 3, ""),
                "industry": _row_value(details, "industry", 3, ""),
                "work_arrangement": _row_value(details, "work_arrangement", 4, "On-site"),
                "location": _row_value(details, "location", 7, ""),
                "deadline": _row_value(details, "enrollment_deadline", 10, ""),
                "hours_per_day": hours_per_day,
                "required_days": required_days or 60,
                "shift_start_time": _row_value(details, "shift_start_time", 15, DEFAULT_START_TIME),
                "shift_end_time": _row_value(details, "shift_end_time", 16, DEFAULT_END_TIME),
                "company_website": _row_value(details, "company_website", 17, ""),
                "company_description": _row_value(details, "company_description", 18, ""),
                "internship_description": _row_value(details, "internship_description", 19, ""),
            }
            selected_days = normalize_attendance_days(_row_value(details, "attendance_days", 14, "")) or list(DEFAULT_ATTENDANCE_DAYS)
            responsibilities = [_row_value(row, "responsibility", 0, "") for row in responsibility_rows]
            qualifications = [_row_value(row, "qualification", 0, "") for row in qualification_rows]
            return _render_edit_form(class_id, form, {}, responsibilities, qualifications, selected_days)

        internship_title = (request.form.get("internship_title") or "").strip()
        company_name = (request.form.get("company_name") or "").strip()
        section = (request.form.get("internship_section") or "").strip()
        industry = (request.form.get("industry") or "").strip()
        work_arrangement = (request.form.get("work_arrangement") or "On-site").strip()
        location = (request.form.get("location") or "").strip()
        deadline = (request.form.get("deadline") or "").strip() or None
        company_website = (request.form.get("company_website") or "").strip()
        company_description = (request.form.get("company_description") or "").strip()
        internship_description = (request.form.get("internship_description") or "").strip()
        responsibilities = [item.strip() for item in request.form.getlist("responsibilities[]") if item.strip()]
        qualifications = [item.strip() for item in request.form.getlist("qualifications[]") if item.strip()]

        errors = {}
        _validate_common_fields(
            errors,
            internship_title,
            company_name,
            section,
            industry,
            work_arrangement,
            location,
            deadline,
            company_website,
            company_description,
            internship_description,
            responsibilities,
            qualifications,
        )
        schedule = _read_schedule_form(errors)
        if errors:
            return _render_edit_form(class_id, request.form, errors, responsibilities, qualifications, schedule["attendance_days"])

        parent_description = f"Internship classroom for {company_name}"
        conn.execute(
            "UPDATE classrooms SET name = ?, section = ?, description = ? WHERE id = ? AND supervisor_id = ?",
            (internship_title, section, parent_description, class_id, supervisor_id),
        )
        conn.execute(
            """
            UPDATE classroom_internship_details
            SET internship_title = ?, program = ?, company_name = ?, industry = ?, work_arrangement = ?,
                schedule_type = 'weekly', hours_mode = 'specified', location = ?,
                enrollment_deadline = ?, hours_per_day = ?, required_days = ?, attendance_days = ?,
                shift_start_time = ?, shift_end_time = ?, required_hours = ?, company_website = ?,
                company_description = ?, internship_description = ?, updated_at = CURRENT_TIMESTAMP
            WHERE classroom_id = ?
            """,
            (
                internship_title,
                schedule["program"],
                company_name,
                industry or None,
                work_arrangement,
                location or None,
                deadline,
                schedule["hours_per_day"],
                schedule["required_days"],
                schedule["attendance_days_text"],
                schedule["shift_start_time"],
                schedule["shift_end_time"],
                schedule["required_hours"],
                company_website or None,
                company_description or None,
                internship_description,
                class_id,
            ),
        )
        conn.execute("DELETE FROM classroom_internship_responsibilities WHERE classroom_id = ?", (class_id,))
        conn.execute("DELETE FROM classroom_internship_qualifications WHERE classroom_id = ?", (class_id,))
        for sort_order, item in enumerate(responsibilities):
            conn.execute(
                "INSERT INTO classroom_internship_responsibilities (classroom_id, responsibility, sort_order) VALUES (?, ?, ?)",
                (class_id, item, sort_order),
            )
        for sort_order, item in enumerate(qualifications):
            conn.execute(
                "INSERT INTO classroom_internship_qualifications (classroom_id, qualification, sort_order) VALUES (?, ?, ?)",
                (class_id, item, sort_order),
            )
        conn.commit()
        flash("Intern Classroom updated successfully.", "success")
        return redirect(url_for("classroom.supervisor_class", class_id=class_id))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Failed to edit intern classroom")
        flash("Failed to update Intern Classroom. Please try again.", "danger")
        if request.method == "POST":
            responsibilities = [item.strip() for item in request.form.getlist("responsibilities[]") if item.strip()]
            qualifications = [item.strip() for item in request.form.getlist("qualifications[]") if item.strip()]
            return _render_edit_form(class_id, request.form, {}, responsibilities, qualifications, _selected_days_from_request())
        return redirect(url_for("classroom.supervisor_class", class_id=class_id))
    finally:
        conn.close()


@internship_classroom.route("/supervisor/classes/<int:class_id>/banner-theme", methods=["POST"])
@role_required("supervisor")
def update_classroom_banner_theme(class_id):
    supervisor_id = session["user_id"]
    banner_theme = (request.form.get("banner_theme") or "").strip().lower()
    return_to = (request.form.get("return_to") or "").strip().lower()

    def _redirect_after_update():
        if return_to == "classes":
            return redirect(url_for("classroom.supervisor_classes"))
        return redirect(url_for("classroom.supervisor_class", class_id=class_id))

    if banner_theme not in _BANNER_THEMES:
        flash("Choose a valid banner color.", "danger")
        return _redirect_after_update()

    conn = get_db_connection()
    try:
        classroom = conn.execute("SELECT supervisor_id FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        if not classroom:
            return "Class not found", 404
        if int(_row_value(classroom, "supervisor_id", 0, 0)) != int(supervisor_id):
            return "Forbidden", 403

        conn.execute(
            "UPDATE classrooms SET banner_theme = ? WHERE id = ? AND supervisor_id = ?",
            (banner_theme, class_id, supervisor_id),
        )
        conn.commit()
        flash("Class banner color updated.", "success")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Failed to update classroom banner color")
        flash("Failed to update the class banner color. Please try again.", "danger")
    finally:
        conn.close()
    return _redirect_after_update()


@internship_classroom.route("/supervisor/classes/<int:class_id>/delete", methods=["POST"])
@role_required("supervisor")
def delete_classroom(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    legacy_files = []
    class_name = "Class"
    try:
        classroom = conn.execute("SELECT supervisor_id, name FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        if not classroom:
            return "Class not found", 404
        if int(_row_value(classroom, "supervisor_id", 0, 0)) != int(supervisor_id):
            return "Forbidden", 403
        class_name = _row_value(classroom, "name", 1, "Class")
        legacy_rows = conn.execute(
            """SELECT s.filepath
               FROM classroom_submissions s
               JOIN classroom_assignments a ON a.id = s.assignment_id
               WHERE a.classroom_id = ? AND s.filepath IS NOT NULL""",
            (class_id,),
        ).fetchall()
        legacy_files = [_row_value(row, "filepath", 0) for row in legacy_rows if _row_value(row, "filepath", 0)]
        conn.execute("DELETE FROM classrooms WHERE id = ? AND supervisor_id = ?", (class_id, supervisor_id))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception("Failed to delete classroom")
        flash("Failed to delete class. Please try again.", "danger")
        return redirect(url_for("classroom.supervisor_class", class_id=class_id))
    finally:
        conn.close()

    upload_root = current_app.config.get("UPLOAD_FOLDER")
    if upload_root:
        root = os.path.abspath(upload_root)
        for filepath in legacy_files:
            try:
                target = os.path.abspath(filepath)
                if os.path.commonpath([root, target]) == root and os.path.isfile(target):
                    os.remove(target)
            except Exception:
                current_app.logger.warning("Could not remove legacy classroom submission file", exc_info=True)
        for folder_name in ("classwork", "classwork_submissions"):
            try:
                base = os.path.abspath(os.path.join(root, folder_name))
                target = os.path.abspath(os.path.join(base, str(class_id)))
                if os.path.commonpath([base, target]) == base and os.path.isdir(target):
                    shutil.rmtree(target, ignore_errors=True)
            except Exception:
                current_app.logger.warning("Could not remove classroom upload directory", exc_info=True)

    flash(f"'{class_name}' was permanently deleted.", "success")
    return redirect(url_for("classroom.supervisor_classes"))
