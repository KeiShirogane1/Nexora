from datetime import datetime, timedelta

from flask import Blueprint, abort, current_app, jsonify, render_template, request, session
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.intern_profile_service import get_supervisor_intern_profile
from app.Services.ojt_evaluation_service import get_supervisor_evaluation_context
from app.Services.performance_report_service import build_student_report

admin_reports_overview = Blueprint("admin_reports_overview", __name__)


def _value(row, key, index=0, default=None):
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


def _as_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _merge_defaults(defaults, value):
    """Return a shallow template-safe mapping while preserving available service data."""
    merged = dict(defaults)
    if isinstance(value, dict):
        merged.update(value)
    return merged


def _empty_student_report():
    """Return the template-safe shape used when optional insight evidence is unavailable."""
    return {
        "performance_label": "No Data",
        "average_percentage": None,
        "min_percentage": None,
        "max_percentage": None,
        "completion_rate": 0.0,
        "graded_count": 0,
        "total_count": 0,
        "assignments": [],
        "strongest": None,
        "weakest": None,
        "priority": "none",
        "recommendation": "",
        "basis": [],
        "sentiment": None,
        "competency": None,
        "has_feedback": False,
        "feedback_analysis": None,
    }


def _safe_student_report(value):
    report = _merge_defaults(_empty_student_report(), value)
    if not isinstance(report.get("assignments"), list):
        report["assignments"] = []
    if not isinstance(report.get("basis"), list):
        report["basis"] = []
    return report


def _safe_attendance(value):
    return _merge_defaults(
        {
            "rendered_hours": 0.0,
            "required_hours": None,
            "remaining_hours": None,
            "progress_percentage": 0.0,
            "progress_percent": 0.0,
            "completed_sessions": 0,
            "total_sessions": 0,
        },
        value,
    )


def _safe_daily_performance(value):
    daily = _merge_defaults({"history": [], "summary": {}}, value)
    if not isinstance(daily.get("history"), list):
        daily["history"] = []
    daily["summary"] = _merge_defaults(
        {
            "average_percentage": None,
            "rated_days": 0,
            "closed_days": 0,
        },
        daily.get("summary"),
    )
    return daily


def _safe_logbook(value):
    return _merge_defaults(
        {
            "total": 0,
            "approved": 0,
            "pending": 0,
            "reviewed": 0,
            "revision_requested": 0,
        },
        value,
    )


def _load_admin_insight_students(conn):
    """Load the Admin insight directory without making optional profile columns fatal."""
    try:
        return conn.execute(
            """
            SELECT u.id, u.username, u.email,
                   COALESCE(sp.first_name, '') AS first_name,
                   COALESCE(sp.last_name, '') AS last_name,
                   COALESCE(sp.student_id, '') AS student_number,
                   COALESCE(sp.major_program, '') AS major_program
            FROM users u
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE u.role = 'student'
              AND EXISTS (
                  SELECT 1
                  FROM classroom_students cs
                  WHERE cs.student_id = u.id
              )
            ORDER BY LOWER(COALESCE(NULLIF(sp.first_name, ''), u.username)),
                     LOWER(COALESCE(NULLIF(sp.last_name, ''), u.email)), u.id
            """
        ).fetchall()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        current_app.logger.exception(
            "Admin Student Insights profile enrichment failed; using account-only directory"
        )
        return conn.execute(
            """
            SELECT u.id, u.username, u.email,
                   '' AS first_name,
                   '' AS last_name,
                   '' AS student_number,
                   '' AS major_program
            FROM users u
            WHERE u.role = 'student'
              AND EXISTS (
                  SELECT 1
                  FROM classroom_students cs
                  WHERE cs.student_id = u.id
              )
            ORDER BY LOWER(u.username), LOWER(u.email), u.id
            """
        ).fetchall()


@admin_reports_overview.route("/admin/reports/student/<int:student_id>/overview")
@role_required("admin")
def overview(student_id):
    conn=get_db_connection()
    try:
        student=conn.execute("SELECT id,username,email FROM users WHERE id=? AND role='student'",(student_id,)).fetchone()
        if not student: abort(404)
        attendance=conn.execute("SELECT clock_in,clock_out,hours_rendered,status FROM attendance WHERE student_id=? ORDER BY clock_in DESC",(student_id,)).fetchall()
        total_hours=sum(float((r[2] if len(r)>2 else 0) or 0) for r in attendance); sessions=len(attendance); completed=sum(1 for r in attendance if (r[3] if len(r)>3 else '')=='Completed')
        feedback=conn.execute("SELECT feedback.comment, feedback.created_at, feedback.performance_label, users.username AS supervisor FROM feedback JOIN users ON users.id=feedback.supervisor_id WHERE feedback.student_id=? ORDER BY feedback.created_at DESC LIMIT 10",(student_id,)).fetchall()
        class_rows=conn.execute("SELECT classroom_id FROM classroom_students WHERE student_id=? ORDER BY classroom_id",(student_id,)).fetchall(); class_ids=[r[0] for r in class_rows]
    finally: conn.close()
    reports=[]
    for cid in class_ids:
        try: reports.append(build_student_report(student_id,int(cid)))
        except Exception: pass
    if reports:
        assignments=[a for r in reports for a in r.get("assignments",[])]; graded=[a for a in assignments if a.get("graded") and a.get("percentage") is not None]; percentages=[float(a["percentage"]) for a in graded]
        report=dict(reports[0]); report.update({"assignments":assignments,"graded_count":len(graded),"total_count":len(assignments),"average_percentage":sum(percentages)/len(percentages) if percentages else None,"min_percentage":min(percentages) if percentages else None,"max_percentage":max(percentages) if percentages else None,"completion_rate":len(graded)/len(assignments)*100 if assignments else 0.0})
        if percentages: report["strongest"]=max(graded,key=lambda x:x["percentage"]); report["weakest"]=min(graded,key=lambda x:x["percentage"])
    else:
        report={"performance_label":"No Data","average_percentage":None,"min_percentage":None,"max_percentage":None,"completion_rate":0.0,"graded_count":0,"total_count":0,"assignments":[],"priority":"none","recommendation":"","sentiment":None,"competency":None}
    return render_template("admin/reports/student_overview.html",student=student,report=report,attendance=attendance,feedback=feedback,total_hours=total_hours,sessions=sessions,completed_sessions=completed,active_page="reports")


@admin_reports_overview.route("/admin/insights")
@role_required("admin")
def student_insights():
    """Read-only, classroom-first student insights for administrators."""
    requested_student_id = request.args.get("student_id", type=int)
    requested_class_id = request.args.get("class_id", type=int)

    selected_classroom = None
    selected_student = None
    students = []

    conn = get_db_connection()
    try:
        classroom_rows = conn.execute(
            """
            SELECT c.id, c.name, c.section, c.code, c.supervisor_id,
                   COALESCE(su.username, '') AS supervisor_name,
                   COALESCE(c.archived, 0) AS archived,
                   COALESCE(c.classroom_type, 'classroom') AS classroom_type,
                   (
                       SELECT COUNT(*)
                       FROM classroom_students cs_count
                       WHERE cs_count.classroom_id = c.id
                   ) AS student_count
            FROM classrooms c
            LEFT JOIN users su ON su.id = c.supervisor_id
            WHERE COALESCE(c.classroom_type, 'classroom') = 'internship'
            ORDER BY COALESCE(c.archived, 0), LOWER(c.name), LOWER(c.section), c.id
            """
        ).fetchall()

        classrooms = [
            {
                "id": int(_value(row, "id", 0, 0)),
                "name": _value(row, "name", 1, "Intern Classroom") or "Intern Classroom",
                "section": _value(row, "section", 2, "") or "",
                "code": _value(row, "code", 3, "") or "",
                "supervisor_id": int(_value(row, "supervisor_id", 4, 0) or 0),
                "supervisor_name": _value(row, "supervisor_name", 5, "") or "",
                "archived": bool(_value(row, "archived", 6, 0)),
                "classroom_type": _value(row, "classroom_type", 7, "internship") or "internship",
                "student_count": int(_value(row, "student_count", 8, 0) or 0),
            }
            for row in classroom_rows
        ]

        if requested_class_id is not None:
            selected_classroom = next(
                (item for item in classrooms if item["id"] == requested_class_id),
                None,
            )
            if selected_classroom is None:
                abort(404)
        elif requested_student_id is not None:
            membership_rows = conn.execute(
                """
                SELECT c.id
                FROM classroom_students cs
                JOIN classrooms c ON c.id = cs.classroom_id
                WHERE cs.student_id = ?
                  AND COALESCE(c.classroom_type, 'classroom') = 'internship'
                ORDER BY COALESCE(c.archived, 0), LOWER(c.name), c.id
                """,
                (requested_student_id,),
            ).fetchall()
            membership_ids = [int(row[0]) for row in membership_rows]
            if len(membership_ids) == 1:
                selected_classroom = next(
                    (item for item in classrooms if item["id"] == membership_ids[0]),
                    None,
                )

        if selected_classroom:
            student_rows = conn.execute(
                """
                SELECT u.id, u.username, u.email,
                       COALESCE(sp.first_name, '') AS first_name,
                       COALESCE(sp.last_name, '') AS last_name,
                       COALESCE(sp.student_id, '') AS student_number,
                       COALESCE(sp.major_program, '') AS major_program
                FROM classroom_students cs
                JOIN users u ON u.id = cs.student_id
                LEFT JOIN student_profiles sp ON sp.user_id = u.id
                WHERE cs.classroom_id = ?
                  AND u.role = 'student'
                ORDER BY LOWER(COALESCE(NULLIF(sp.first_name, ''), u.username)),
                         LOWER(COALESCE(NULLIF(sp.last_name, ''), u.email)), u.id
                """,
                (selected_classroom["id"],),
            ).fetchall()
            students = [
                {
                    "id": int(_value(row, "id", 0, 0)),
                    "username": _value(row, "username", 1, "") or "",
                    "email": _value(row, "email", 2, "") or "",
                    "first_name": _value(row, "first_name", 3, "") or "",
                    "last_name": _value(row, "last_name", 4, "") or "",
                    "student_number": _value(row, "student_number", 5, "") or "",
                    "major_program": _value(row, "major_program", 6, "") or "",
                }
                for row in student_rows
            ]
            for item in students:
                item["display_name"] = (
                    " ".join(
                        part
                        for part in (item["first_name"], item["last_name"])
                        if part
                    ).strip()
                    or item["username"]
                    or "Student"
                )

            if requested_student_id is not None:
                selected_student = next(
                    (item for item in students if item["id"] == requested_student_id),
                    None,
                )
                if selected_student is None:
                    abort(404)
    finally:
        conn.close()

    context = None
    insights_warnings = []
    if selected_student and selected_classroom:
        try:
            report = _safe_student_report(
                build_student_report(selected_student["id"], selected_classroom["id"])
            )
        except Exception:
            current_app.logger.exception(
                "Admin Student Insights Work/ML evidence failed for student_id=%s class_id=%s",
                selected_student["id"],
                selected_classroom["id"],
            )
            report = _empty_student_report()
            insights_warnings.append("Work and ML evidence is temporarily unavailable.")

        try:
            profile = get_supervisor_intern_profile(
                supervisor_id=selected_classroom["supervisor_id"],
                classroom_id=selected_classroom["id"],
                student_id=selected_student["id"],
            )
        except Exception:
            current_app.logger.exception(
                "Admin Student Insights OJT evidence failed for student_id=%s class_id=%s",
                selected_student["id"],
                selected_classroom["id"],
            )
            profile = {"ok": True}
            insights_warnings.append(
                "Attendance, Daily Performance, and Logbook evidence is temporarily unavailable."
            )
        else:
            if not isinstance(profile, dict) or not profile.get("ok"):
                current_app.logger.warning(
                    "Admin Student Insights OJT evidence unavailable for student_id=%s class_id=%s status=%s",
                    selected_student["id"],
                    selected_classroom["id"],
                    profile.get("status_code") if isinstance(profile, dict) else None,
                )
                profile = {"ok": True}
                insights_warnings.append(
                    "Attendance, Daily Performance, and Logbook evidence is temporarily unavailable."
                )

        try:
            evaluation_context = get_supervisor_evaluation_context(
                supervisor_id=selected_classroom["supervisor_id"],
                classroom_id=selected_classroom["id"],
                student_id=selected_student["id"],
            )
        except Exception:
            current_app.logger.exception(
                "Admin Student Insights Official Evaluation failed for student_id=%s class_id=%s",
                selected_student["id"],
                selected_classroom["id"],
            )
            evaluation_context = {"ok": True, "evaluation": None}
            insights_warnings.append("Official OJT Evaluation is temporarily unavailable.")
        else:
            if not isinstance(evaluation_context, dict) or not evaluation_context.get("ok"):
                current_app.logger.warning(
                    "Admin Student Insights Official Evaluation unavailable for student_id=%s class_id=%s status=%s",
                    selected_student["id"],
                    selected_classroom["id"],
                    evaluation_context.get("status_code")
                    if isinstance(evaluation_context, dict)
                    else None,
                )
                evaluation_context = {"ok": True, "evaluation": None}
                insights_warnings.append("Official OJT Evaluation is temporarily unavailable.")

        context = {
            "report": _safe_student_report(report),
            "attendance": _safe_attendance(profile.get("attendance_summary")),
            "daily_performance": _safe_daily_performance(profile.get("daily_performance")),
            "logbook": _safe_logbook(profile.get("logbook_summary")),
            "official_evaluation": evaluation_context.get("evaluation"),
        }

    return render_template(
        "admin/student_insights.html",
        students=students,
        selected_student=selected_student,
        classrooms=classrooms,
        selected_classroom=selected_classroom,
        insights=context,
        insights_warnings=insights_warnings,
        active_page="reports",
    )


@admin_reports_overview.route("/supervisor/dashboard/activity-chart")
@role_required("supervisor")
def supervisor_activity_chart():
    """Return a portable date-bucketed activity series for the dashboard chart."""
    days = request.args.get("days", default=7, type=int)
    if days not in {1, 7, 14, 21, 30}:
        days = 7

    supervisor_id = session["user_id"]
    now = datetime.now()
    chart_days = [
        (now - timedelta(days=offset)).date()
        for offset in range(days - 1, -1, -1)
    ]
    chart_start = datetime.combine(chart_days[0], datetime.min.time())
    chart_index = {day: index for index, day in enumerate(chart_days)}

    conn = get_db_connection()
    try:
        log_rows = conn.execute(
            """
            SELECT COALESCE(l.updated_at, l.created_at) AS activity_at
            FROM logs l
            JOIN attendance a ON a.id = l.attendance_id
            JOIN classrooms c ON c.id = a.classroom_id
            WHERE l.entry_type = 'daily'
              AND c.supervisor_id = ?
              AND COALESCE(l.updated_at, l.created_at) >= ?
            """,
            (supervisor_id, chart_start),
        ).fetchall()
        work_rows = conn.execute(
            """
            SELECT s.submitted_at
            FROM classwork_submissions s
            JOIN classroom_assignments a ON a.id = s.assignment_id
            JOIN classrooms c ON c.id = a.classroom_id
            WHERE c.supervisor_id = ?
              AND s.submitted_at >= ?
            """,
            (supervisor_id, chart_start),
        ).fetchall()
        evaluation_rows = conn.execute(
            """
            SELECT COALESCE(e.submitted_at, e.updated_at, e.created_at) AS activity_at
            FROM ojt_evaluations e
            WHERE e.supervisor_id = ?
              AND COALESCE(e.submitted_at, e.updated_at, e.created_at) >= ?
            """,
            (supervisor_id, chart_start),
        ).fetchall()
    finally:
        conn.close()

    def bucket(rows, key, index=0):
        counts = [0] * len(chart_days)
        for row in rows:
            dt = _as_datetime(_value(row, key, index, None))
            if dt and dt.date() in chart_index:
                counts[chart_index[dt.date()]] += 1
        return counts

    return jsonify(
        {
            "days": days,
            "label": "Today" if days == 1 else f"Last {days} Days",
            "labels": [f"{day.strftime('%b')} {day.day}" for day in chart_days],
            "logbook": bucket(log_rows, "activity_at"),
            "work": bucket(work_rows, "submitted_at"),
            "evaluations": bucket(evaluation_rows, "activity_at"),
        }
    )