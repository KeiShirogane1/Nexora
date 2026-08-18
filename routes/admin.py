from flask import Blueprint, render_template, session, request, redirect
import sqlite3
from routes.security import role_required
import os
from database.db import get_db_connection
from datetime import datetime
from collections import Counter
from ml.predictor import analyze_feedback

def format_date(timestamp):
    if not timestamp:
        return None

    return datetime.fromisoformat(timestamp).strftime("%b %d, %Y")

def format_time(timestamp):
    if not timestamp:
        return None

    return datetime.fromisoformat(timestamp).strftime("%I:%M %p").lstrip("0")

def format_datetime(timestamp):
    if not timestamp:
        return None

    return datetime.fromisoformat(timestamp).strftime("%b %d, %Y • %I:%M %p").lstrip("0")

admin = Blueprint("admin", __name__)

@admin.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    conn = sqlite3.connect("nexora.db")
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users WHERE role='student'")
    students_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE role='supervisor'")
    supervisors_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM student_assignments")
    assignments_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM feedback")
    feedback_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE status = 'Open'")
    online_interns = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(hours_rendered), 0) FROM attendance WHERE status = 'Completed'")
    total_hours = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "admin/dashboard.html",
        students_count=students_count,
        supervisors_count=supervisors_count,
        assignments_count=assignments_count,
        feedback_count=feedback_count,
        online_interns=online_interns,
        total_hours=total_hours,
        active_page="dashboard"
    )

@admin.route("/admin/users")
@role_required("admin")
def admin_users():
    conn = sqlite3.connect("nexora.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, username, role
        FROM users
        ORDER BY role, username
    """)

    users = cursor.fetchall()
    conn.close()

    return render_template("admin/users.html", users=users, active_page="users")

@admin.route("/admin/assign", methods=["GET", "POST"])
@role_required("admin")
def assign_students():

    conn = sqlite3.connect("nexora.db")
    cursor = conn.cursor()

    # SUBMIT ASSIGNMENT
    if request.method == "POST":
        student_id = request.form["student_id"]
        supervisor_id = request.form["supervisor_id"]

        cursor.execute("""
            INSERT INTO student_assignments (student_id, supervisor_id)
            VALUES (?, ?)
        """, (student_id, supervisor_id))

        conn.commit()

    # LOAD DROPDOWNS
    cursor.execute("SELECT id, username FROM users WHERE role='student'")
    students = cursor.fetchall()

    cursor.execute("SELECT id, username FROM users WHERE role='supervisor'")
    supervisors = cursor.fetchall()

    # CURRENT ASSIGNMENTS (IMPORTANT FOR DEFENSE)
    cursor.execute("""
        SELECT sa.student_id, s.username, sa.supervisor_id, sup.username
        FROM student_assignments sa
        JOIN users s ON sa.student_id = s.id
        JOIN users sup ON sa.supervisor_id = sup.id
    """)
    assignments = cursor.fetchall()

    conn.close()

    return render_template(
        "admin/assign.html",
        students=students,
        supervisors=supervisors,
        assignments=assignments,
        active_page="assign"
    )

@admin.route("/admin/reports")
@role_required("admin")
def admin_reports_list():

    conn = sqlite3.connect("nexora.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            s.id,
            s.username,
            COALESCE(sup.username, 'Not Assigned')
        FROM users s

        LEFT JOIN student_assignments sa
            ON s.id = sa.student_id

        LEFT JOIN users sup
            ON sa.supervisor_id = sup.id

        WHERE s.role = 'student'

        ORDER BY s.username ASC
    """)

    students = cursor.fetchall()

    conn.close()

    return render_template(
        "admin/reports_list.html",
        students=students,
        active_page="reports"
    )

@admin.route("/admin/reports/<int:student_id>")
@role_required("admin")
def admin_reports(student_id):

    conn = sqlite3.connect("nexora.db")
    cursor = conn.cursor()

    # student info
    cursor.execute("SELECT username FROM users WHERE id = ?", (student_id,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return "Student not found"

    # logs (same as supervisor)
    cursor.execute("""
        SELECT content, created_at
        FROM logs
        WHERE student_id = ?
    """, (student_id,))
    logs = cursor.fetchall()

    # tasks (same as supervisor)
    cursor.execute("""
        SELECT task_title, task_description, assigned_at, status
        FROM tasks
        WHERE student_id = ?
    """, (student_id,))
    tasks = cursor.fetchall()

    # feedback (supervisor evaluation)
    cursor.execute("""
        SELECT comment, created_at
        FROM feedback
        WHERE student_id = ?
    """, (student_id,))
    feedback = cursor.fetchall()

    # documents (student uploads)
    cursor.execute("""
        SELECT filename, uploaded_at
        FROM documents
        WHERE student_id = ?
    """, (student_id,))
    documents = cursor.fetchall()

    conn.close()

    return render_template(
        "admin/reports.html",
        student=student,
        logs=logs,
        tasks=tasks,
        feedback=feedback,
        documents=documents,
        active_page="reports"
    )

@admin.route("/admin/assignments")
@role_required("admin")
def admin_assignments():

    conn = sqlite3.connect("nexora.db")
    cursor = conn.cursor()

    # students & supervisors
    cursor.execute("SELECT id, username FROM users WHERE role='student'")
    students = cursor.fetchall()

    cursor.execute("SELECT id, username FROM users WHERE role='supervisor'")
    supervisors = cursor.fetchall()

    # assignments
    cursor.execute("""
        SELECT sa.student_id, s.username, sa.supervisor_id, sup.username
        FROM student_assignments sa
        JOIN users s ON sa.student_id = s.id
        JOIN users sup ON sa.supervisor_id = sup.id
    """)
    assignments = cursor.fetchall()

    # pending users (THIS is Step 2)
    cursor.execute("""
        SELECT id, username
        FROM users
        WHERE role='pending'
    """)
    pending_users = cursor.fetchall()

    conn.close()

    return render_template(
        "admin/assignments.html",
        students=students,
        supervisors=supervisors,
        assignments=assignments,
        pending_users=pending_users,
        active_page="assign"
    )

@admin.route('/admin/assign-role', methods=['GET', 'POST'])
@role_required("admin")
def assign_role():

    user_id = request.form["user_id"]
    new_role = request.form["role"]

    conn = sqlite3.connect("nexora.db")
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET role = ?
        WHERE id = ?
    """, (new_role, user_id))

    conn.commit()
    conn.close()

    return redirect("/admin/assignments")

# Reports generation #

# Overall version reports

#attendance and logbook report
@admin.route("/admin/reports/attendance")
@role_required("admin")
def attendance_report():

    conn = get_db_connection()

    # SEARCH

    search = request.args.get("search", "").strip()

    # PAGINATION

    page = request.args.get("page", 1, type=int)

    per_page = 10

    offset = (page - 1) * per_page

    # TOTAL NUMBER OF INTERNS

    total_interns = conn.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE role = 'student'
        AND username LIKE ?
    """, (f"%{search}%",)).fetchone()[0]

    total_pages = (total_interns + per_page - 1) // per_page

    # INTERN SUMMARY

    interns = conn.execute("""
        SELECT
            users.id,
            users.username,

            (
                SELECT COUNT(*)
                FROM attendance
                WHERE attendance.student_id = users.id
            ) AS total_sessions,

            (
                SELECT COALESCE(SUM(hours_rendered), 0)
                FROM attendance
                WHERE attendance.student_id = users.id
            ) AS total_hours,

            (
                SELECT COUNT(*)
                FROM logs
                WHERE logs.student_id = users.id
            ) AS total_logs

        FROM users

        WHERE users.role = 'student'
        AND users.username LIKE ?

        ORDER BY users.username ASC

        LIMIT ?
        OFFSET ?
    """, (f"%{search}%", per_page, offset)).fetchall()

    # overall metrics

    total_sessions = conn.execute("""
        SELECT COUNT(*)
        FROM attendance
    """).fetchone()[0]

    total_hours = conn.execute("""
        SELECT COALESCE(SUM(hours_rendered), 0)
        FROM attendance
    """).fetchone()[0]

    completed_sessions = conn.execute("""
        SELECT COUNT(*)
        FROM attendance
        WHERE status = 'Completed'
    """).fetchone()[0]

    total_logs = conn.execute("""
        SELECT COUNT(*)
        FROM logs
    """).fetchone()[0]

    conn.close()

    return render_template(
        "admin/reports/attendance.html",

        interns=interns,

        total_sessions=total_sessions,
        total_hours=total_hours,
        completed_sessions=completed_sessions,
        total_logs=total_logs,

        search=search,
        page=page,
        total_pages=total_pages,

        active_page="reports"
    )

# Individual version reports

@admin.route("/admin/reports/student/<int:student_id>")
@role_required("admin")
def student_report(student_id):

    active_tab = request.args.get("tab", "overview")

    conn = get_db_connection()

    student = conn.execute("""
        SELECT id, username
        FROM users
        WHERE id = ?
        AND role = 'student'
    """, (student_id,)).fetchone()

    if not student:
        conn.close()
        return "Student not found"


    # attendance table

    attendance = conn.execute("""
        SELECT
            id,
            clock_in,
            clock_out,
            hours_rendered,
            status
        FROM attendance
        WHERE student_id = ?
        ORDER BY clock_in DESC
    """, (student_id,)).fetchall()

    attendance = [
    (
        session[0],
        format_date(session[1]),
        format_time(session[1]),
        format_time(session[2]),
        session[3],
        session[4]
    )
    for session in attendance
]


# ATTENDANCE PAGINATION

    attendance_per_page = 10

    attendance_page = request.args.get(
        "attendance_page",
        1,
        type=int
    )

    if attendance_page < 1:
        attendance_page = 1

    total_sessions = len(attendance)

    attendance_total_pages = (
        (total_sessions + attendance_per_page - 1)
        // attendance_per_page
    )

    if attendance_total_pages > 0 and attendance_page > attendance_total_pages:
        attendance_page = attendance_total_pages

    attendance_start = (
        attendance_page - 1
    ) * attendance_per_page

    attendance_end = (
        attendance_start + attendance_per_page
    )

    attendance_display = attendance[
        attendance_start:attendance_end
    ]


    total_hours = sum(
        session[4] or 0
        for session in attendance
    )

    average_hours = (
        total_hours / total_sessions
        if total_sessions > 0
        else 0
    )


    # logbook section

    acts = conn.execute("""
        SELECT
            id,
            attendance_id,
            content,
            created_at
        FROM logs
        WHERE student_id = ?
        ORDER BY created_at DESC
    """, (student_id,)).fetchall()

    acts = [
        (
            act[0],
            act[1],
            act[2],
            format_datetime(act[3])
        )
        for act in acts
    ]

    total_logs = len(acts)



    # group logbook entries by date

    log_dates = conn.execute("""
        SELECT
            created_at
        FROM logs
        WHERE student_id = ?
        ORDER BY created_at DESC
    """, (student_id,)).fetchall()


    logbook_days = {}

    for log in log_dates:

        date_value = datetime.fromisoformat(log[0]).strftime("%Y-%m-%d")
        display_date = format_date(log[0])

        if date_value not in logbook_days:

            logbook_days[date_value] = {
                "date": display_date,
                "url_date": date_value,
                "entries": 0
            }

        logbook_days[date_value]["entries"] += 1


    logbook_days = list(logbook_days.values())

    # LOGBOOK PAGINATION

    logbook_per_page = 5

    logbook_page = request.args.get(
        "logbook_page",
        1,
        type=int
    )

    if logbook_page < 1:
        logbook_page = 1

    total_logbook_days = len(logbook_days)

    logbook_total_pages = (
        (total_logbook_days + logbook_per_page - 1)
        // logbook_per_page
    )

    if logbook_total_pages > 0 and logbook_page > logbook_total_pages:
        logbook_page = logbook_total_pages

    logbook_start = (
        logbook_page - 1
    ) * logbook_per_page

    logbook_end = (
        logbook_start + logbook_per_page
    )

    logbook_display = logbook_days[
        logbook_start:logbook_end
    ]


    # attendance interpretation

    if total_sessions == 0:

        attendance_interpretation = (
            "No attendance sessions have been recorded for this intern yet."
        )

    elif total_hours == 0:

        attendance_interpretation = (
            f"The intern has recorded {total_sessions} "
            f"attendance session"
            f"{'s' if total_sessions != 1 else ''}, "
            "but no completed rendered hours are currently available."
        )

    else:

        attendance_interpretation = (
            f"The intern has recorded {total_sessions} "
            f"attendance session"
            f"{'s' if total_sessions != 1 else ''}, "
            f"with {total_hours:.1f} total hours rendered "
            f"and {total_logs} logbook entr"
            f"{'ies' if total_logs != 1 else 'y'}."
        )


    # Evaluations/Feedback with ML section 

    feedback = conn.execute("""
        SELECT
            feedback.comment,
            feedback.created_at,
            feedback.performance_label,
            users.username
        FROM feedback
        JOIN users
            ON feedback.supervisor_id = users.id
        WHERE feedback.student_id = ?
        ORDER BY feedback.created_at DESC
    """, (student_id,)).fetchall()


    feedback = [
        (
            fb[0],
            format_datetime(fb[1]),
            fb[2],
            fb[3],
            analyze_feedback(fb[0])
        )
        for fb in feedback
    ]


    total_feedback = len(feedback)


    # ML CLASSIFICATION SUMMARY

    ml_predictions = [
        fb[4]
        for fb in feedback
        if fb[4]
    ]


    ml_counts = Counter(ml_predictions)


    # Keep a consistent order for the report

    ml_categories = [
        "Excellent",
        "Very Satisfactory",
        "Satisfactory",
        "Fair",
        "Needs Improvement"
    ]


    ml_distribution = [
        {
            "label": category,
            "count": ml_counts.get(category, 0)
        }
        for category in ml_categories
    ]


    # OVERALL ML CLASSIFICATION

    if ml_predictions:

        prediction_counts = Counter(ml_predictions)

        highest_count = max(
        prediction_counts.values()
        )

        top_categories = [
            label
            for label, count in prediction_counts.items()
            if count == highest_count
        ]

        if len(top_categories) == 1:

            overall_ml_analysis = top_categories[0]

        else:

            overall_ml_analysis = "Mixed"

    else:

        overall_ml_analysis = None


    # ML STRUCTURED INSIGHT

    if not ml_predictions:

        ml_insight = (
            "No supervisor feedback is available for ML analysis yet."
        )

    else:

        prediction_counts = Counter(ml_predictions)

        highest_count = max(
            prediction_counts.values()
        )

        top_categories = [
            label
            for label, count in prediction_counts.items()
            if count == highest_count
        ]


        total_analyzed = len(ml_predictions)


        if len(top_categories) == 1:

            dominant_label = top_categories[0]

            dominant_count = prediction_counts[dominant_label]

            ml_insight = (
                f"Supervisor feedback is predominantly classified as "
                f"{dominant_label}, accounting for "
                f"{dominant_count} of {total_analyzed} "
                f"evaluation"
                f"{'s' if total_analyzed != 1 else ''}."
            )

        else:

            category_text = ", ".join(top_categories)

            ml_insight = (
                f"Supervisor feedback shows a mixed classification, "
                f"with {category_text} tied as the most frequent "
                f"category at {highest_count} evaluation"
                f"{'s' if highest_count != 1 else ''} each."
            )


    # tasks list

        # TASKS / PROGRESS

    tasks = conn.execute("""
        SELECT
            id,
            task_title,
            status,
            assigned_at,
            deadline
        FROM tasks
        WHERE student_id = ?
        ORDER BY assigned_at DESC
    """, (student_id,)).fetchall()


    total_tasks = len(tasks)


    completed_tasks = sum(
        1
        for task in tasks
        if task[2] in ("Submitted", "Reviewed")
    )


    pending_tasks = sum(
        1
        for task in tasks
        if task[2] == "Pending"
    )


    reopened_tasks = sum(
        1
        for task in tasks
        if task[2] == "Reopened"
    )


    task_progress = (
        (completed_tasks / total_tasks) * 100
        if total_tasks > 0
        else 0
    )


    # PROGRESS INTERPRETATION

    if total_tasks == 0:

        progress_interpretation = (
            "No internship tasks have been assigned to this intern yet."
        )

    else:

        progress_interpretation = (
            f"The intern has completed {completed_tasks} "
            f"out of {total_tasks} assigned task"
            f"{'s' if total_tasks != 1 else ''}, "
            f"representing a {task_progress:.1f}% completion rate."
        )

        if pending_tasks > 0:

            progress_interpretation += (
                f" {pending_tasks} pending task"
                f"{'s' if pending_tasks != 1 else ''} "
                "remain"
                f"{'s' if pending_tasks != 0 else ''} "
                "unresolved."
            )

        if reopened_tasks > 0:

            progress_interpretation += (
                f" {reopened_tasks} task"
                f"{'s' if reopened_tasks != 1 else ''} "
                "have been reopened and may require further action."
            )

        if total_hours > 0:

            progress_interpretation += (
                f" The intern has also rendered "
                f"{total_hours:.1f} hours across "
                f"{total_sessions} attendance session"
                f"{'s' if total_sessions != 1 else ''}."
            )


    conn.close()

    return render_template(
        "admin/reports/student_report.html",
        student=student,

        # Attendance & Logbook
        attendance=attendance_display,
        attendance_page=attendance_page,
        attendance_total_pages=attendance_total_pages,
        acts=acts,
        total_sessions=total_sessions,
        total_hours=total_hours,
        average_hours=average_hours,
        total_logs=total_logs,
        attendance_interpretation=attendance_interpretation,
        logbook_days=logbook_display,
        logbook_page=logbook_page,
        logbook_total_pages=logbook_total_pages,

        # Evaluations
        feedback=feedback,
        total_feedback=total_feedback,
        ml_distribution=ml_distribution,
        overall_ml_analysis=overall_ml_analysis,
        ml_insight=ml_insight,

        # Tasks / Progress
        tasks=tasks,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        reopened_tasks=reopened_tasks,
        task_progress=task_progress,
        progress_interpretation=progress_interpretation,

        active_tab=active_tab,
        active_page="reports"
    )

# By-date logs

@admin.route("/admin/reports/student/<int:student_id>/logbook/<date>")
@role_required("admin")
def student_logbook(student_id, date):

    conn = get_db_connection()

    # GET STUDENT

    student = conn.execute("""
        SELECT id, username
        FROM users
        WHERE id = ?
        AND role = 'student'
    """, (student_id,)).fetchone()

    if not student:
        conn.close()
        return "Student not found"


    # VALIDATE DATE

    try:
        report_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        conn.close()
        return "Invalid date"


    # FORMAT DATE FOR DISPLAY

    display_date = report_date.strftime("%b %d, %Y")


    # GET ATTENDANCE FOR THIS DATE

    attendance = conn.execute("""
        SELECT
            id,
            clock_in,
            clock_out,
            hours_rendered,
            status
        FROM attendance
        WHERE student_id = ?
        AND date(clock_in) = ?
        ORDER BY clock_in ASC
    """, (student_id, date)).fetchall()


    attendance = [
        (
            session[0],
            format_time(session[1]),
            format_time(session[2]),
            session[3],
            session[4]
        )
        for session in attendance
    ]


    # GET LOGBOOK ENTRIES FOR THIS DATE

    logs = conn.execute("""
        SELECT
            id,
            attendance_id,
            content,
            created_at
        FROM logs
        WHERE student_id = ?
        AND date(created_at) = ?
        ORDER BY created_at ASC
    """, (student_id, date)).fetchall()


    logs = [
        (
            log[0],
            log[1],
            log[2],
            format_time(log[3])
        )
        for log in logs
    ]


    total_logs = len(logs)

    total_hours = sum(
        session[3] or 0
        for session in attendance
    )


    conn.close()


    return render_template(
        "admin/reports/student_logbook.html",
        student=student,
        display_date=display_date,
        attendance=attendance,
        logs=logs,
        total_logs=total_logs,
        total_hours=total_hours
    )