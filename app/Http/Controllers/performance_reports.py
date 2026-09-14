"""Performance Reports — supervisor and student views with CSV/PDF export."""

import csv
from io import StringIO

from flask import Blueprint, abort, make_response, render_template, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.intern_profile_service import get_supervisor_intern_profile
from app.Services.ojt_evaluation_service import get_supervisor_evaluation_context
from app.Services.pdf_export_service import build_report_pdf, slugify_filename_part
from app.Services.performance_report_service import build_class_reports, build_student_report

performance_reports = Blueprint("performance_reports", __name__)


def _value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            return row[key]
    except AttributeError:
        pass
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return default


def _normalize_report_evidence(report):
    """Prevent no-evidence reports from presenting a real performance result."""
    if not isinstance(report, dict):
        return report

    normalized = dict(report)
    has_performance_data = (
        normalized.get("overall_percentage") is not None
        and int(normalized.get("graded_count", 0) or 0) > 0
    )
    normalized["has_performance_data"] = has_performance_data
    if has_performance_data:
        return normalized

    normalized["performance_label"] = "No Data"
    normalized["performance_classification"] = "No Data"
    normalized["recommendation"] = ""
    normalized["priority"] = "none"

    basis = [
        item for item in (normalized.get("basis") or [])
        if not str(item).lower().startswith("performance label:")
    ]
    basis.insert(0, "performance label: No Data")
    normalized["basis"] = basis

    recommendation = dict(normalized.get("ml_recommendation") or {})
    recommendation.update(
        {
            "performance_label": "No Data",
            "overall_percentage": None,
            "recommendation": "",
            "priority": "none",
            "basis": basis,
        }
    )
    normalized["ml_recommendation"] = recommendation
    return normalized


def _owned_classroom(supervisor_id, class_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, name, section, code, description, archived FROM classrooms WHERE id=? AND supervisor_id=?",
            (class_id, supervisor_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        abort(404)
    return {
        "id": _value(row, "id", 0),
        "name": _value(row, "name", 1, "Intern Classroom"),
        "section": _value(row, "section", 2, ""),
        "code": _value(row, "code", 3, ""),
        "description": _value(row, "description", 4, ""),
        "archived": bool(_value(row, "archived", 5, 0)),
    }


def _csv_download(filename, rows):
    output = StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerows(rows)
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _pdf_download(filename, content):
    response = make_response(content)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _fmt_number(value, digits=1, suffix=""):
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def _individual_insights_export_context(supervisor_id, class_id, student_id):
    classroom = _owned_classroom(supervisor_id, class_id)
    report = _normalize_report_evidence(build_student_report(student_id, class_id))
    profile = get_supervisor_intern_profile(
        supervisor_id=supervisor_id,
        classroom_id=class_id,
        student_id=student_id,
    )
    if not profile.get("ok"):
        abort(int(profile.get("status_code") or 404))

    evaluation_context = get_supervisor_evaluation_context(
        supervisor_id=supervisor_id,
        classroom_id=class_id,
        student_id=student_id,
    )
    if not evaluation_context.get("ok"):
        abort(int(evaluation_context.get("status_code") or 404))

    student = profile.get("student") or report.get("student") or {}
    return {
        "classroom": classroom,
        "student": student,
        "report": report,
        "attendance": profile.get("attendance_summary") or {},
        "daily": profile.get("daily_performance") or {"history": [], "summary": {}},
        "logbook": profile.get("logbook_summary") or {},
        "evaluation": evaluation_context.get("evaluation"),
    }


# Supervisor: class reports listing
@performance_reports.route("/supervisor/classes/<int:class_id>/reports")
@role_required("supervisor")
def supervisor_reports(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            "SELECT id, supervisor_id, name, section, description, code, archived FROM classrooms WHERE id=? AND supervisor_id=?",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
            abort(404)
        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 2),
            "section": _value(classroom, "section", 3),
            "description": _value(classroom, "description", 4),
            "code": _value(classroom, "code", 5),
            "archived": _value(classroom, "archived", 6),
        }
    finally:
        conn.close()

    reports = [_normalize_report_evidence(report) for report in build_class_reports(class_id)]

    return render_template(
        "classroom/supervisor_reports.html",
        classroom=classroom_data,
        reports=reports,
        active_page="classes",
    )


# Supervisor: individual student report
@performance_reports.route("/supervisor/classes/<int:class_id>/reports/<int:student_id>")
@role_required("supervisor")
def supervisor_student_report(class_id, student_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            "SELECT id, supervisor_id, name, section, code FROM classrooms WHERE id=? AND supervisor_id=?",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
            abort(404)
        membership = conn.execute(
            "SELECT 1 FROM classroom_students WHERE classroom_id=? AND student_id=?",
            (class_id, student_id),
        ).fetchone()
        if not membership:
            abort(404)
        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 2),
            "section": _value(classroom, "section", 3),
            "code": _value(classroom, "code", 4),
        }
    finally:
        conn.close()

    report = _normalize_report_evidence(build_student_report(student_id, class_id))
    profile = get_supervisor_intern_profile(
        supervisor_id=supervisor_id,
        classroom_id=class_id,
        student_id=student_id,
    )
    if not profile.get("ok"):
        abort(int(profile.get("status_code") or 404))

    evaluation_context = get_supervisor_evaluation_context(
        supervisor_id=supervisor_id,
        classroom_id=class_id,
        student_id=student_id,
    )
    if not evaluation_context.get("ok"):
        abort(int(evaluation_context.get("status_code") or 404))

    return render_template(
        "classroom/supervisor_student_report.html",
        classroom=classroom_data,
        report=report,
        attendance_summary=profile.get("attendance_summary") or {},
        daily_performance=profile.get("daily_performance") or {"history": [], "summary": {}},
        logbook_summary=profile.get("logbook_summary") or {},
        official_evaluation=evaluation_context.get("evaluation"),
        active_page="classes",
    )


# Supervisor: CSV export
@performance_reports.route("/supervisor/classes/<int:class_id>/reports/export.csv")
@role_required("supervisor")
def export_supervisor_reports(class_id):
    supervisor_id = session["user_id"]
    classroom = _owned_classroom(supervisor_id, class_id)
    reports = [_normalize_report_evidence(report) for report in build_class_reports(class_id)]

    rows = [[
        "Student Number",
        "Student",
        "Email",
        "Work Average %",
        "Work Completion %",
        "Work Performance",
        "Competency",
        "Sentiment",
        "Recommendation",
        "Priority",
    ]]
    for report in reports:
        student = report.get("student") or {}
        recommendation = report.get("ml_recommendation") or {}
        rows.append([
            student.get("student_number", "") or "",
            student.get("username", "") or "",
            student.get("email", "") or "",
            "" if report.get("overall_percentage") is None else f"{report.get('overall_percentage'):.1f}",
            f"{report.get('completion_rate', 0):.1f}",
            report.get("performance_label", "") or "",
            (report.get("competency") or "") if report.get("competency") is not None else (recommendation.get("competency") or ""),
            (report.get("sentiment") or "") if report.get("sentiment") is not None else "",
            (report.get("recommendation") or recommendation.get("recommendation") or "").replace("\n", " ").strip(),
            report.get("priority") or recommendation.get("priority", "") or "",
        ])
    filename = f"nexora-performance-report-{slugify_filename_part(classroom['name'], 'class')}.csv"
    return _csv_download(filename, rows)


# Supervisor: overall classroom Insights exports
@performance_reports.route("/supervisor/classes/<int:class_id>/insights/export.csv")
@role_required("supervisor")
def export_supervisor_insights_csv(class_id):
    supervisor_id = session["user_id"]
    classroom = _owned_classroom(supervisor_id, class_id)
    reports = [_normalize_report_evidence(report) for report in build_class_reports(class_id)]
    rows = [[
        "Student Number", "Student", "Email", "Work Average %", "Work Completion %",
        "Work Label", "Sentiment", "Competency", "Recommendation", "Priority",
    ]]
    for report in reports:
        student = report.get("student") or {}
        rows.append([
            student.get("student_number") or "",
            student.get("username") or "",
            student.get("email") or "",
            "" if report.get("overall_percentage") is None else f"{report.get('overall_percentage'):.1f}",
            f"{float(report.get('completion_rate') or 0):.1f}",
            report.get("performance_label") or "No Data",
            report.get("sentiment") or "",
            report.get("competency") or "",
            (report.get("recommendation") or "").replace("\n", " ").strip(),
            report.get("priority") or "",
        ])
    filename = f"nexora-insights-{slugify_filename_part(classroom['name'], 'class')}.csv"
    return _csv_download(filename, rows)


@performance_reports.route("/supervisor/classes/<int:class_id>/insights/export.pdf")
@role_required("supervisor")
def export_supervisor_insights_pdf(class_id):
    supervisor_id = session["user_id"]
    classroom = _owned_classroom(supervisor_id, class_id)
    reports = [_normalize_report_evidence(report) for report in build_class_reports(class_id)]
    table_rows = []
    for report in reports:
        student = report.get("student") or {}
        table_rows.append([
            student.get("username") or "Student",
            _fmt_number(report.get("overall_percentage"), 1, "%"),
            _fmt_number(report.get("completion_rate"), 1, "%"),
            report.get("performance_label") or "No Data",
            report.get("sentiment") or "—",
            (report.get("priority") or "none").title(),
        ])
    pdf = build_report_pdf(
        "Nexora Classroom Insights",
        f"{classroom['name']} · {classroom['section'] or 'No section'}",
        sections=[
            {
                "heading": "Classroom Summary",
                "rows": [
                    ("Classroom", classroom["name"]),
                    ("Section", classroom["section"] or "—"),
                    ("Class Code", classroom["code"] or "—"),
                    ("Interns", len(reports)),
                ],
            },
            {
                "heading": "Work and ML Insights",
                "headers": ["Intern", "Work Avg", "Completion", "Work Label", "Sentiment", "Priority"],
                "table": table_rows,
            },
        ],
        footer_note="ML Insights are decision-support evidence only and do not create or replace the Official OJT Evaluation.",
        landscape_mode=True,
    )
    filename = f"nexora-insights-{slugify_filename_part(classroom['name'], 'class')}.pdf"
    return _pdf_download(filename, pdf)


# Supervisor: individual Insights exports
@performance_reports.route("/supervisor/classes/<int:class_id>/insights/<int:student_id>/export.csv")
@role_required("supervisor")
def export_supervisor_individual_insights_csv(class_id, student_id):
    context = _individual_insights_export_context(session["user_id"], class_id, student_id)
    classroom = context["classroom"]
    student = context["student"]
    report = context["report"]
    attendance = context["attendance"]
    daily_summary = (context["daily"].get("summary") or {})
    logbook = context["logbook"]
    evaluation = context["evaluation"]
    display_name = student.get("display_name") or student.get("username") or (report.get("student") or {}).get("username") or "student"

    rows = [
        ["Dimension", "Metric", "Value"],
        ["Identity", "Student", display_name],
        ["Identity", "Classroom", classroom["name"]],
        ["Attendance & OJT Hours", "Rendered Hours", _fmt_number(attendance.get("rendered_hours"), 2)],
        ["Attendance & OJT Hours", "Required Hours", _fmt_number(attendance.get("required_hours"), 1)],
        ["Attendance & OJT Hours", "Progress", _fmt_number(attendance.get("progress_percentage"), 1, "%")],
        ["Daily Performance", "Average", _fmt_number(daily_summary.get("average_percentage"), 1, "%")],
        ["Daily Performance", "Rated Days", daily_summary.get("rated_days", 0)],
        ["Daily Logbook", "Entries", logbook.get("total", 0)],
        ["Daily Logbook", "Approved", logbook.get("approved", 0)],
        ["Daily Logbook", "Pending", logbook.get("pending", 0)],
        ["Work", "Average", _fmt_number(report.get("overall_percentage"), 1, "%")],
        ["Work", "Completion", _fmt_number(report.get("completion_rate"), 1, "%")],
        ["Work", "Classification", report.get("performance_label") or "No Data"],
        ["Feedback ML", "Sentiment", report.get("sentiment") or "—"],
        ["Feedback ML", "Competency", report.get("competency") or "—"],
        ["Decision Support", "Recommendation", report.get("recommendation") or "No Work-based recommendation available"],
        ["Official Evaluation", "Status", (evaluation.get("status") if evaluation else "Not started")],
        ["Official Evaluation", "Manual Overall Score", _fmt_number(evaluation.get("overall_score") if evaluation else None, 1)],
    ]
    student_slug = slugify_filename_part(display_name, "student")
    class_slug = slugify_filename_part(classroom["name"], "class")
    return _csv_download(f"nexora-insights-{student_slug}-{class_slug}.csv", rows)


@performance_reports.route("/supervisor/classes/<int:class_id>/insights/<int:student_id>/export.pdf")
@role_required("supervisor")
def export_supervisor_individual_insights_pdf(class_id, student_id):
    context = _individual_insights_export_context(session["user_id"], class_id, student_id)
    classroom = context["classroom"]
    student = context["student"]
    report = context["report"]
    attendance = context["attendance"]
    daily_summary = context["daily"].get("summary") or {}
    logbook = context["logbook"]
    evaluation = context["evaluation"]
    display_name = student.get("display_name") or student.get("username") or (report.get("student") or {}).get("username") or "Student"

    pdf = build_report_pdf(
        "Nexora Individual Insights",
        f"{display_name} · {classroom['name']} · {classroom['section'] or 'No section'}",
        sections=[
            {
                "heading": "Evidence Overview",
                "rows": [
                    ("Attendance / OJT Hours", f"{_fmt_number(attendance.get('rendered_hours'), 2)} hrs"),
                    ("Hours Progress", _fmt_number(attendance.get("progress_percentage"), 1, "%")),
                    ("Daily Performance", _fmt_number(daily_summary.get("average_percentage"), 1, "%")),
                    ("Rated Days", daily_summary.get("rated_days", 0)),
                    ("Daily Logbook Entries", logbook.get("total", 0)),
                    ("Approved Logbook", logbook.get("approved", 0)),
                ],
            },
            {
                "heading": "Work and ML Decision Support",
                "rows": [
                    ("Work Average", _fmt_number(report.get("overall_percentage"), 1, "%")),
                    ("Work Completion", _fmt_number(report.get("completion_rate"), 1, "%")),
                    ("Work Classification", report.get("performance_label") or "No Data"),
                    ("Sentiment", report.get("sentiment") or "—"),
                    ("Competency Signal", report.get("competency") or "—"),
                    ("Recommendation", report.get("recommendation") or "No Work-based recommendation available"),
                    ("Priority", (report.get("priority") or "none").title()),
                ],
            },
            {
                "heading": "Official OJT Evaluation",
                "rows": [
                    ("Status", evaluation.get("status", "Not started") if evaluation else "Not started"),
                    ("Manual Overall Score", _fmt_number(evaluation.get("overall_score") if evaluation else None, 1)),
                    ("Remarks", evaluation.get("remarks") or "—" if evaluation else "—"),
                ],
            },
        ],
        footer_note="OJT Hours, Daily Performance, Logbook, Work analytics, feedback ML, and Official Evaluation remain separate evidence dimensions. Nexora does not calculate a combined OJT grade from them.",
    )
    student_slug = slugify_filename_part(display_name, "student")
    class_slug = slugify_filename_part(classroom["name"], "class")
    return _pdf_download(f"nexora-insights-{student_slug}-{class_slug}.pdf", pdf)


# Student: own report only
@performance_reports.route("/student/classes/<int:class_id>/reports")
@role_required("student")
def student_reports(class_id):
    student_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            """SELECT c.id, c.name, c.section, c.code, c.supervisor_id, u.username AS sup_name
               FROM classrooms c
               JOIN users u ON u.id=c.supervisor_id
               JOIN classroom_students cs ON cs.classroom_id=c.id
               WHERE c.id=? AND cs.student_id=?""",
            (class_id, student_id),
        ).fetchone()
        if not classroom:
            abort(404)
        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 1),
            "section": _value(classroom, "section", 2),
            "code": _value(classroom, "code", 3),
            "supervisor": _value(classroom, "sup_name", 5, ""),
        }
    finally:
        conn.close()

    report = _normalize_report_evidence(build_student_report(student_id, class_id))

    return render_template(
        "classroom/student_report.html",
        classroom=classroom_data,
        report=report,
        active_page="classes",
    )
