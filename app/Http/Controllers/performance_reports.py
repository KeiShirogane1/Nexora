"""Performance Reports — supervisor and student views with CSV export."""

import csv
from io import StringIO

from flask import Blueprint, abort, make_response, render_template, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
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


# Supervisor: class reports listing
@performance_reports.route("/supervisor/classes/<int:class_id>/reports")
@role_required("supervisor")
def supervisor_reports(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            "SELECT id, supervisor_id, name, section, code, archived FROM classrooms WHERE id=? AND supervisor_id=?",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
            abort(404)
        classroom_data = {
            "id": _value(classroom, "id", 0),
            "name": _value(classroom, "name", 2),
            "section": _value(classroom, "section", 3),
            "code": _value(classroom, "code", 4),
            "archived": _value(classroom, "archived", 5),
        }
    finally:
        conn.close()

    reports = build_class_reports(class_id)

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
        # Verify student belongs to class
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

    report = build_student_report(student_id, class_id)

    return render_template(
        "classroom/supervisor_student_report.html",
        classroom=classroom_data,
        report=report,
        active_page="classes",
    )


# Supervisor: CSV export
@performance_reports.route("/supervisor/classes/<int:class_id>/reports/export.csv")
@role_required("supervisor")
def export_supervisor_reports(class_id):
    supervisor_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute(
            "SELECT id, name FROM classrooms WHERE id=? AND supervisor_id=?",
            (class_id, supervisor_id),
        ).fetchone()
        if not classroom:
            abort(404)
        cname = _value(classroom, "name", 1, "class")
    finally:
        conn.close()

    reports = build_class_reports(class_id)

    output = StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(
        [
            "Student Number",
            "Student",
            "Email",
            "Overall %",
            "Completion %",
            "Performance",
            "Competency",
            "Sentiment",
            "Recommendation",
            "Priority",
        ]
    )
    for r in reports:
        stu = r.get("student") or {}
        reco = r.get("ml_recommendation") or {}
        writer.writerow(
            [
                stu.get("student_number", "") or "",
                stu.get("username", "") or "",
                stu.get("email", "") or "",
                "" if r.get("overall_percentage") is None else f"{r.get('overall_percentage'):.1f}",
                f"{r.get('completion_rate', 0):.1f}",
                r.get("performance_label", "") or "",
                (r.get("competency") or "") if r.get("competency") is not None else (reco.get("competency") or ""),
                (r.get("sentiment") or "") if r.get("sentiment") is not None else "",
                (r.get("recommendation") or reco.get("recommendation") or "").replace("\n", " ").strip(),
                r.get("priority") or reco.get("priority", "") or "",
            ]
        )
    filename = f"reports-{str(cname).strip().replace(' ', '-')}.csv"
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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

    report = build_student_report(student_id, class_id)

    return render_template(
        "classroom/student_report.html",
        classroom=classroom_data,
        report=report,
        active_page="classes",
    )
