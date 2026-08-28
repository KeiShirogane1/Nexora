from flask import Blueprint, render_template, session, request, redirect, url_for, flash
from routes.security import role_required
from services.email_service import (
    send_email,
    send_profile_updated_email
)
from services.profile_service import (
    update_student_profile,
    get_student_profile_data
)
from services.profile_history_service import (
    log_profile_change,
    get_profile_history
)

from services.notification_service import (
    create_notification
)
import os
from database.db import get_db_connection
from datetime import datetime
from collections import Counter
from ml.predictor import analyze_feedback
import secrets
import string
<<<<<<< Updated upstream
=======

from security.password_security import hash_password
>>>>>>> Stashed changes

from security.password_security import hash_password

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

def generate_temp_password():

    chars = string.ascii_letters + string.digits

    password = "".join(
        secrets.choice(chars)
        for _ in range(10)
    )

    return password


@admin.route(
    "/student/<int:student_id>/reset-password"
)
def reset_student_password(student_id):

    conn = get_db_connection()
    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
            id,
            username,
            email
        FROM users
        WHERE id = ?
        """,
        (student_id,)
    )


    student = cursor.fetchone()


    if not student:

        flash(
            "Student not found.",
            "danger"
        )

        return redirect(
            url_for("admin.admin_students")
        )


    temporary_password = generate_temp_password()


    hashed_password = hash_password(
        temporary_password
    )


    cursor.execute(
        """
        UPDATE users
        SET password = ?
        WHERE id = ?
        """,
        (
            hashed_password,
            student_id
        )
    )


    conn.commit()


    cursor.close()
    conn.close()



    try:

        send_email(
            student["email"],
            "Nexora Temporary Password",
            f"""
    Hello {student["username"]},

    Your Nexora account password has been reset by the administrator.

    Your temporary password is:

    {temporary_password}

    Please login and change your password after signing in.

    Nexora System
    """
        )

    except Exception as e:

        flash(
            f"Password reset but email failed: {e}",
            "warning"
        )

        return redirect(
            url_for(
                "admin.student_profile",
                student_id=student_id
            )
        )


    flash(
        "Temporary password sent to student email.",
        "success"
    )


    return redirect(
        url_for(
            "admin.student_profile",
            student_id=student_id
        )
    )

@admin.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    conn = get_db_connection()
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
    
        # INTERNSHIP STATUS SUMMARY

    cursor.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE role='pending_student'
    """)
    pending_students = cursor.fetchone()[0]


    cursor.execute("""
        SELECT COUNT(*)
        FROM internships
        WHERE status='Active'
    """)
    active_internships = cursor.fetchone()[0]


    cursor.execute("""
        SELECT COUNT(*)
        FROM internships
        WHERE status='Completed'
    """)
    completed_internships = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "admin/dashboard.html",
        students_count=students_count,
        supervisors_count=supervisors_count,
        assignments_count=assignments_count,
        feedback_count=feedback_count,
        online_interns=online_interns,
        total_hours=total_hours,
        active_page="dashboard",
        pending_students=pending_students,
        active_internships=active_internships,
        completed_internships=completed_internships
    )

@admin.route("/admin/users")
@role_required("admin")
def admin_users():

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        # ALL USERS
        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                role
            FROM users
            ORDER BY username
            """
        )

        users = cursor.fetchall()



        # STUDENTS
        students = [
            user for user in users
            if user["role"] == "student"
        ]



        # SUPERVISORS
        supervisors = [
            user for user in users
            if user["role"] == "supervisor"
        ]



        # PENDING ACCOUNTS
        pending_users = [
            user for user in users
            if user["role"] in (
                "pending_student",
                "pending_supervisor"
            )
        ]



        # TOTAL USERS
        total_users = len(users)



        # COUNTS
        students_count = len(students)

        supervisors_count = len(supervisors)

        pending_count = len(pending_users)



        return render_template(
            "admin/users.html",

            active_page="users",

            students=students,

            supervisors=supervisors,

            pending_users=pending_users,

            total_users=total_users,

            students_count=students_count,

            supervisors_count=supervisors_count,

            pending_count=pending_count
        )


    finally:

        cursor.close()
        conn.close()


@admin.route("/admin/users/students")
@role_required("admin")
def admin_students():

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                role
            FROM users
            WHERE role IN 
            (
                'student',
                'pending_student'
            )
            ORDER BY username
            """
        )

        students = cursor.fetchall()


        return render_template(
            "admin/students.html",
            students=students,
            active_page="users"
        )


    finally:
        cursor.close()
        conn.close()


@admin.route("/admin/student/<int:student_id>")
@role_required("admin")
def student_profile(student_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                users.id,
                users.username,
                users.email,
                users.role,
                users.status,

                student_profiles.*

            FROM users

            LEFT JOIN student_profiles
            ON users.id = student_profiles.user_id

            WHERE users.id = ?

        """, (student_id,))


        student = cursor.fetchone()


        if not student:
            return "Student not found"


        profile_fields = [
            "first_name",
            "last_name",
            "student_id",
            "profile_picture",
            "phone_number",
            "home_address",
            "grade_year",
            "major_program",
            "emergency_name",
            "emergency_phone"
        ]


        completed_fields = 0
        missing_fields = []


        for field in profile_fields:

            if student[field]:

                completed_fields += 1

            else:

                missing_fields.append(
                    field.replace("_", " ").title()
                )


        completion_percentage = int(
            (completed_fields / len(profile_fields)) * 100
        )
        
                # INTERNSHIP INFORMATION

        cursor.execute("""
            SELECT
                company_name,
                company_address,
                supervisor_name,
                supervisor_email,
                position,
                start_date,
                end_date,
                required_hours,
                completed_hours,
                status

            FROM internships

            WHERE student_id = ?

            ORDER BY id DESC

            LIMIT 1

        """, (student_id,))


        internship = cursor.fetchone()
        
                # STUDENT DOCUMENTS

        cursor.execute("""
            SELECT
                filename,
                uploaded_at
            FROM documents

            WHERE student_id = ?

            ORDER BY uploaded_at DESC

        """, (student_id,))


        documents = cursor.fetchall()


        return render_template(
            "admin/student_profile.html",
            student=student,
            completion_percentage=completion_percentage,
            missing_fields=missing_fields,
            internship=internship,
            documents=documents,
            active_page="users"
        )


    finally:

        cursor.close()
        conn.close()
        

@admin.route("/admin/users/supervisors")
@role_required("admin")
def admin_supervisors():

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                role
            FROM users
            WHERE role IN
            (
                'supervisor',
                'pending_supervisor'
            )
            ORDER BY username
            """
        )

        supervisors = cursor.fetchall()


        return render_template(
            "admin/supervisors.html",
            supervisors=supervisors,
            active_page="users"
        )


    finally:
        cursor.close()
        conn.close()
        
        
@admin.route("/admin/student/edit/<int:student_id>", methods=["GET", "POST"])
@role_required("admin")
def edit_student(student_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                users.id,
                users.username,
                users.email,
                student_profiles.*

            FROM users

            LEFT JOIN student_profiles
            ON users.id = student_profiles.user_id

            WHERE users.id = ?

        """,(student_id,))


        student = cursor.fetchone()


        if not student:
            return "Student not found"


        student_email = student["email"]

        student_username = student["username"]


        if request.method == "POST":


            profile_data = get_student_profile_data(
                request.form
            )


            update_student_profile(
                student_id,
                profile_data
            )


            log_profile_change(
                student_id,
                session["user_id"],
                "Admin updated student profile"
            )


            create_notification(
                student_id,
                "Profile Updated",
                "An administrator updated your profile information.",
                "info"
            )


            conn.commit()


            if student_email:

                try:

                    send_profile_updated_email(
                        student_email,
                        student_username,
                        session.get("username", "Administrator")
                    )

                except Exception as e:

                    print(
                        "Profile update email failed:",
                        e
                    )


            return redirect(
                url_for(
                    "admin.student_profile",
                    student_id=student_id
                )
            )


        return render_template(
            "admin/edit_student.html",
            student=student
        )


    finally:

        cursor.close()
        conn.close()        
        
        

@admin.route("/admin/assign", methods=["GET", "POST"])
@role_required("admin")
def assign_students():

    conn = get_db_connection()
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

    conn = get_db_connection()
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

    conn = get_db_connection()
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

    conn = get_db_connection()
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
        SELECT id, username, role
        FROM users
        WHERE role IN
        (
            'pending_student',
            'pending_supervisor'
        )
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
    
@admin.route("/admin/reject-student/<int:user_id>")
@role_required("admin")
def reject_student(user_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT username, email
            FROM users
            WHERE id = ?
            AND role = 'pending_student'
            """,
            (user_id,)
        )

        user = cursor.fetchone()


        if not user:
            return redirect(
                "/admin/users/students"
            )


        cursor.execute(
            """
            UPDATE users
            SET role = 'rejected'
            WHERE id = ?
            AND role = 'pending_student'
            """,
            (user_id,)
        )


        conn.commit()


        if user["email"]:

            try:

                send_email(
                    user["email"],
                    "Nexora Account Request Cancelled",
                    f"""
Hello {user["username"]},

Your Nexora student account request was not approved.

Please contact the Nexora administrator for more information.

Nexora System
                    """.strip()
                )

            except Exception as e:

                print(
                    "Rejection email failed:",
                    e
                )


    finally:

        cursor.close()
        conn.close()


    return redirect(
        "/admin/users/students"
    )
    
@admin.route("/admin/approve-student/<int:user_id>")
@role_required("admin")
def approve_student(user_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT username, email
            FROM users
            WHERE id = ?
            AND role = 'pending_student'
            """,
            (user_id,)
        )

        user = cursor.fetchone()


        if not user:
            return redirect(
                "/admin/users/students"
            )


        cursor.execute(
            """
            UPDATE users
            SET role = 'student'
            WHERE id = ?
            AND role = 'pending_student'
            """,
            (user_id,)
        )

        conn.commit()


        # Send approval email
        if user["email"]:

            try:

                send_email(
                    user["email"],
                    "Nexora Account Approved",
                    f"""
                    Hello {user["username"]},

                    Your Nexora student account has been approved.

                    You may now login and complete your student profile.

                    Welcome to Nexora.

                    Nexora System
                    """.strip()
                )

            except Exception as e:

                print(
                    "Approval email failed:",
                    e
                )


    finally:

        cursor.close()
        conn.close()


    return redirect(
        "/admin/users/students"
    )
    
    
@admin.route("/admin/internship-assign", methods=["GET", "POST"])
@role_required("admin")
def internship_assign():

    conn = get_db_connection()
    cursor = conn.cursor()


    if request.method == "POST":

        student_id = request.form["student_id"]

        company_name = request.form["company_name"]
        company_address = request.form["company_address"]
        supervisor_name = request.form["supervisor_name"]
        supervisor_email = request.form["supervisor_email"]
        position = request.form["position"]

        start_date = request.form["start_date"]
        end_date = request.form["end_date"]

        required_hours = request.form["required_hours"]


        cursor.execute("""
            INSERT INTO internships
            (
                student_id,
                company_name,
                company_address,
                supervisor_name,
                supervisor_email,
                position,
                start_date,
                end_date,
                required_hours,
                completed_hours,
                status
            )

            VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        """,
        (
            student_id,
            company_name,
            company_address,
            supervisor_name,
            supervisor_email,
            position,
            start_date,
            end_date,
            required_hours,
            0,
            "Active"
        ))


        conn.commit()


    cursor.execute("""
        SELECT id, username
        FROM users
        WHERE role='student'
        ORDER BY username
    """)

    students = cursor.fetchall()


    conn.close()


    return render_template(
        "admin/internship_assign.html",
        students=students,
        active_page="internship"
    )    


@admin.route('/admin/assign-role', methods=['GET', 'POST'])
@role_required("admin")
def assign_role():

    user_id = request.form["user_id"]
    new_role = request.form["role"]

    conn = get_db_connection()
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
    
@admin.route(
    "/student/<int:student_id>/deactivate",
    methods=["GET"]
)
@role_required("admin")
def deactivate_student(student_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                username,
                email
            FROM users
            WHERE id = ?
            """,
            (student_id,)
        )

        student = cursor.fetchone()


        if not student:

            flash(
                "Student not found.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin.admin_students"
                )
            )


        cursor.execute(
            """
            UPDATE users
            SET status = ?
            WHERE id = ?
            """,
            (
                "inactive",
                student_id
            )
        )


        conn.commit()



        if student["email"]:

            try:

                send_email(
                    student["email"],
                    "Nexora Account Deactivated",
                    f"""
Hello {student["username"]},

Your Nexora student account has been deactivated by the administrator.

You will no longer be able to access the system until your account is activated again.

If you believe this was a mistake, please contact the Nexora administrator.

Nexora System
                    """.strip()
                )

            except Exception as e:

                print(
                    "Deactivation email failed:",
                    e
                )


        flash(
            "Student account has been deactivated.",
            "success"
        )


    finally:

        cursor.close()
        conn.close()


    return redirect(
        url_for(
            "admin.student_profile",
            student_id=student_id
        )
    )
    
    
@admin.route(
    "/student/<int:student_id>/activate",
    methods=["GET"]
)
@role_required("admin")
def activate_student(student_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                username,
                email
            FROM users
            WHERE id = ?
            """,
            (student_id,)
        )

        student = cursor.fetchone()


        if not student:

            flash(
                "Student not found.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin.admin_students"
                )
            )


        cursor.execute(
            """
            UPDATE users
            SET status = ?
            WHERE id = ?
            """,
            (
                "active",
                student_id
            )
        )


        conn.commit()



        if student["email"]:

            try:

                send_email(
                    student["email"],
                    "Nexora Account Activated",
                    f"""
Hello {student["username"]},

Your Nexora student account has been activated.

You may now login and continue using the Nexora system.

Welcome back.

Nexora System
                    """.strip()
                )

            except Exception as e:

                print(
                    "Activation email failed:",
                    e
                )


        flash(
            "Student account has been activated.",
            "success"
        )


    finally:

        cursor.close()
        conn.close()


    return redirect(
        url_for(
            "admin.student_profile",
            student_id=student_id
        )
    )
    
    
    # ============================
# PROFILE HISTORY
# ============================

@admin.route(
    "/admin/student/history/<int:student_id>"
)
@role_required("admin")
def profile_history(student_id):


    conn = get_db_connection()
    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
            profile_history.action,
            profile_history.created_at,
            users.username

        FROM profile_history

        LEFT JOIN users
        ON profile_history.changed_by = users.id

        WHERE profile_history.student_id = ?

        ORDER BY profile_history.created_at DESC

        """,
        (
            student_id,
        )
    )


    history = cursor.fetchall()


    cursor.close()
    conn.close()


    return render_template(
        "admin/profile_history.html",
        history=history,
        student_id=student_id
    )