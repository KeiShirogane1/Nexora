from flask import Blueprint, render_template, session, request, redirect, url_for, flash, current_app
from app.Http.Middleware.security import role_required
from app.Services.email_service import (
    send_email,
    send_profile_updated_email
)
from app.Services.profile_service import (
    update_student_profile,
    get_student_profile_data,
    normalize_program_name
)
from app.Services.profile_history_service import (
    log_profile_change,
    get_profile_history
)

from app.Services.notification_service import (
    create_notification
)
from app.Services.account_approval_service import (
    approve_pending_user,
    reject_pending_user,
    process_due_pending_accounts,
    get_pending_account_view,
)
import os
from app.Models.db import get_db_connection, using_postgres
from datetime import datetime, timedelta
from collections import Counter
from app.ML.predictor import analyze_feedback, analyze_feedback_detailed
import secrets
import string

from app.Services.password_security import hash_password

def parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    return datetime.fromisoformat(value)


def format_date(timestamp):
    dt = parse_datetime(timestamp)

    if not dt:
        return None

    return dt.strftime("%b %d, %Y")


def format_time(timestamp):
    dt = parse_datetime(timestamp)

    if not dt:
        return None

    return dt.strftime("%I:%M %p").lstrip("0")


def format_datetime(timestamp):
    dt = parse_datetime(timestamp)

    if not dt:
        return None

    return dt.strftime("%b %d, %Y • %I:%M %p").lstrip("0")

admin = Blueprint("admin", __name__)

def generate_temp_password():
    # 12 chars, cryptographically secure, alphanumeric + symbols for thesis demo
    # Use secrets.token_urlsafe for URL-safe, or choice from 72-char set
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    # 12 chars from 72-char alphabet ≈ 74 bits entropy, > 10-char (59 bits)
    return "".join(secrets.choice(alphabet) for _ in range(12))


@admin.route(
    "/student/<int:student_id>/reset-password",
    methods=["POST"]
)
@role_required("admin")
def reset_student_password(student_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
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
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    if student["email"]:

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

    else:

        flash(
            "Password reset. The student has no email on file, so give them the temporary password manually.",
            "warning"
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

    try:
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
    finally:
        cursor.close()
        conn.close()

@admin.route("/admin/users")
@role_required("admin")
def admin_users():
    try:
        process_due_pending_accounts()
    except Exception as exc:
        current_app.logger.warning(
            "Could not process due account approvals on Admin User Management: %s",
            exc,
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                role,
                created_at
            FROM users
            WHERE role != 'deleted'
            ORDER BY username
            """
        )
        users = cursor.fetchall()

        students = [
            user for user in users
            if user["role"] == "student"
        ]

        supervisors = [
            user for user in users
            if user["role"] == "supervisor"
        ]

        pending_users = [
            get_pending_account_view(user)
            for user in users
            if user["role"] in (
                "pending_student",
                "pending_supervisor"
            )
        ]

        total_users = len(users)
        students_count = len(students)
        supervisors_count = len(supervisors)
        pending_count = len(pending_users)
        highlight_pending_user_id = request.args.get(
            "pending_user",
            type=int,
        )

        return render_template(
            "admin/users.html",
            active_page="users",
            students=students,
            supervisors=supervisors,
            pending_users=pending_users,
            total_users=total_users,
            students_count=students_count,
            supervisors_count=supervisors_count,
            pending_count=pending_count,
            highlight_pending_user_id=highlight_pending_user_id,
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
            SELECT DISTINCT
                users.id,
                users.username,
                users.email,
                users.role,
                student_profiles.major_program,
                student_profiles.created_at AS joined_at,
                sup.username AS supervisor_name
            FROM users
            LEFT JOIN student_profiles
                ON users.id = student_profiles.user_id
            LEFT JOIN student_assignments sa
                ON users.id = sa.student_id
            LEFT JOIN users sup
                ON sa.supervisor_id = sup.id
            WHERE users.role IN (
                'student',
                'pending_student'
            )
            ORDER BY users.username
            """
        )

        student_rows = cursor.fetchall()
        students = []
        for row in student_rows:
            student = {key: row[key] for key in row.keys()}
            student["joined_date"] = format_date(student.get("joined_at"))
            students.append(student)


        # Fetch only real database values for the Admin program selector.
        cursor.execute("SELECT id, username FROM users WHERE role='supervisor' ORDER BY username")
        supervisors_list = cursor.fetchall()
        cursor.execute("SELECT DISTINCT major_program FROM student_profiles WHERE major_program IS NOT NULL AND major_program != ''")
        programs_raw = [r[0] for r in cursor.fetchall() if r[0]]
        programs = sorted(
            {normalize_program_name(value) for value in programs_raw if value},
            key=str.casefold,
        )
        programs_count = len(programs)

        # --- Add new KPI query ---
        kpi_sql = """
        SELECT
            COUNT(*) AS total_students,
            COALESCE(SUM(
                CASE
                    WHEN role = 'student'
                     AND COALESCE(status, 'active') = 'active'
                    THEN 1 ELSE 0
                END
            ), 0) AS active_students,
            COALESCE(SUM(
                CASE
                    WHEN role = 'pending_student'
                    THEN 1 ELSE 0
                END
            ), 0) AS pending_students,
            COALESCE(SUM(
                CASE
                    WHEN role = 'student'
                     AND status = 'inactive'
                    THEN 1 ELSE 0
                END
            ), 0) AS inactive_students
        FROM users
        WHERE role IN ('student', 'pending_student')
        """
        cursor.execute(kpi_sql)
        kpi_counts = cursor.fetchone()

        total_students_kpi = kpi_counts['total_students'] if kpi_counts else 0
        active_students_kpi = kpi_counts['active_students'] if kpi_counts else 0
        pending_students_kpi = kpi_counts['pending_students'] if kpi_counts else 0
        inactive_students_kpi = kpi_counts['inactive_students'] if kpi_counts else 0
        # --- End of new KPI query ---
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_students,
                COALESCE(SUM(
                    CASE
                        WHEN role = 'student'
                         AND COALESCE(status, 'active') = 'active'
                        THEN 1 ELSE 0
                    END
                ), 0) AS active_students,
                COALESCE(SUM(
                    CASE
                        WHEN role = 'pending_student'
                        THEN 1 ELSE 0
                    END
                ), 0) AS pending_students,
                COALESCE(SUM(
                    CASE
                        WHEN role = 'student'
                         AND status = 'inactive'
                        THEN 1 ELSE 0
                    END
                ), 0) AS inactive_students
            FROM users
            WHERE role IN ('student', 'pending_student')
            """
        )
        kpi_counts = cursor.fetchone()
        total_students = kpi_counts[0] if kpi_counts else 0
        active_students = kpi_counts[1] if kpi_counts else 0
        pending_students = kpi_counts[2] if kpi_counts else 0
        inactive_students = kpi_counts[3] if kpi_counts else 0
        programs_count = len(programs)

        return render_template(
            "admin/students.html",
            students=students,
            supervisors_list=supervisors_list,
            programs=programs,
            total_students=total_students,
            active_students=active_students,
            pending_students=pending_students,
            inactive_students=inactive_students,
            programs_count=programs_count,
            active_page="users"
        )


    finally:
        cursor.close()
        conn.close()


@admin.route("/admin/users/students/create", methods=["POST"])
@role_required("admin")
def create_student():
    import re
    from flask import jsonify

    # Support both JSON and form-data
    data = request.get_json(silent=True) or request.form

    full_name = (data.get("full_name") or "").strip()
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    program = normalize_program_name(data.get("program"))
    supervisor_id = (data.get("supervisor_id") or data.get("supervisor") or "").strip()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or data.get("confirmPassword") or ""

    errors = {}

    # Required fields
    if not full_name:
        errors["full_name"] = "Full name is required."
    elif len(full_name) < 2:
        errors["full_name"] = "Full name is too short."

    if not username:
        errors["username"] = "Username is required."
    elif len(username) < 3:
        errors["username"] = "Username must be at least 3 characters."
    elif not re.match(r"^[A-Za-z0-9_.-]+$", username):
        errors["username"] = "Username may only contain letters, numbers, _ . -"

    if not email:
        errors["email"] = "Email is required."
    elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        errors["email"] = "Invalid email format."

    if not program:
        errors["program"] = "Program is required."

    if not password:
        errors["password"] = "Password is required."
    elif len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."

    if password != confirm_password:
        errors["confirm_password"] = "Passwords do not match."

    # Supervisor optional but if provided must exist
    supervisor_id_int = None
    if supervisor_id:
        try:
            supervisor_id_int = int(supervisor_id)
        except:
            errors["supervisor_id"] = "Invalid supervisor."
            supervisor_id_int = None

    if errors:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": errors}), 400
        for field, msg in errors.items():
            flash(f"{field}: {msg}", "danger")
        return redirect(url_for("admin.admin_students"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Uniqueness checks (parameterized)
        cursor.execute("SELECT id FROM users WHERE username = ? OR LOWER(email) = LOWER(?)", (username, email))
        existing = cursor.fetchone()
        if existing:
            # Determine which field duplicates
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                errors["username"] = "Username already exists."
            cursor.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(?)", (email,))
            if cursor.fetchone():
                errors["email"] = "Email already exists."
            if errors:
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"success": False, "errors": errors}), 400
                for f, m in errors.items():
                    flash(f"{f}: {m}", "danger")
                return redirect(url_for("admin.admin_students"))

        # Validate supervisor exists if provided
        if supervisor_id_int is not None:
            cursor.execute("SELECT id FROM users WHERE id = ? AND role = 'supervisor'", (supervisor_id_int,))
            if not cursor.fetchone():
                errors["supervisor_id"] = "Selected supervisor not found."
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"success": False, "errors": errors}), 400
                flash("Selected supervisor not found.", "danger")
                return redirect(url_for("admin.admin_students"))

        password_hash = hash_password(password)

        # Split full name
        parts = full_name.strip().split()
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        middle_name = None

        cursor.execute(
            "INSERT INTO users (username, email, password, role, status, password_changed_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (username, email, password_hash, "student", "active")
        )
        user_id = cursor.lastrowid

        # Create student profile with only existing columns
        cursor.execute(
            """
            INSERT INTO student_profiles (user_id, first_name, middle_name, last_name, major_program, profile_completed)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (user_id, first_name, middle_name, last_name, program)
        )

        if supervisor_id_int is not None:
            # Postgres-compatible: use ON CONFLICT DO NOTHING (works on SQLite 3.24+ and Postgres)
            if using_postgres():
                cursor.execute(
                    "INSERT INTO student_assignments (student_id, supervisor_id) VALUES (?, ?) ON CONFLICT (student_id, supervisor_id) DO NOTHING",
                    (user_id, supervisor_id_int)
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO student_assignments (student_id, supervisor_id) VALUES (?, ?)",
                    (user_id, supervisor_id_int)
                )

        conn.commit()

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "message": "Student created successfully.", "user_id": user_id})
        flash("Student account created successfully.", "success")
        return redirect(url_for("admin.admin_students"))

    except Exception as e:
        conn.rollback()
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": {"_general": str(e)}}), 500
        flash(f"Failed to create student: {e}", "danger")
        return redirect(url_for("admin.admin_students"))
    finally:
        cursor.close()
        conn.close()


@admin.route("/admin/users/supervisors/create", methods=["POST"])
@role_required("admin")
def create_supervisor():
    import re
    from flask import jsonify

    data = request.get_json(silent=True) or request.form

    full_name = (data.get("full_name") or "").strip()
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or data.get("confirmPassword") or ""

    errors = {}

    if not full_name:
        errors["full_name"] = "Full name is required."
    elif len(full_name) < 2:
        errors["full_name"] = "Full name is too short."

    if not username:
        errors["username"] = "Username is required."
    elif len(username) < 3:
        errors["username"] = "Username must be at least 3 characters."
    elif not re.match(r"^[A-Za-z0-9_.-]+$", username):
        errors["username"] = "Username may only contain letters, numbers, _ . -"

    if not email:
        errors["email"] = "Email is required."
    elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        errors["email"] = "Invalid email format."

    if not password:
        errors["password"] = "Password is required."
    elif len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."

    if password != confirm_password:
        errors["confirm_password"] = "Passwords do not match."

    if errors:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": errors}), 400
        for f, m in errors.items():
            flash(f"{f}: {m}", "danger")
        return redirect(url_for("admin.admin_supervisors"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE username = ? OR LOWER(email) = LOWER(?)", (username, email))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                errors["username"] = "Username already exists."
            cursor.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(?)", (email,))
            if cursor.fetchone():
                errors["email"] = "Email already exists."
            if errors:
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"success": False, "errors": errors}), 400
                for f, m in errors.items():
                    flash(f"{f}: {m}", "danger")
                return redirect(url_for("admin.admin_supervisors"))

        password_hash = hash_password(password)

        cursor.execute(
            "INSERT INTO users (username, email, password, role, status, password_changed_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (username, email, password_hash, "supervisor", "active")
        )
        user_id = cursor.lastrowid
        conn.commit()

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "message": "Supervisor created successfully.", "user_id": user_id})
        flash("Supervisor account created successfully.", "success")
        return redirect(url_for("admin.admin_supervisors"))

    except Exception as e:
        conn.rollback()
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": {"_general": str(e)}}), 500
        flash(f"Failed to create supervisor: {e}", "danger")
        return redirect(url_for("admin.admin_supervisors"))
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
                role,
                status
            FROM users
            WHERE role IN
            (
                'supervisor',
                'pending_supervisor'
            )
            AND role != 'deleted'
            ORDER BY username
            """
        )

        supervisors = cursor.fetchall()

        # Assigned student counts per supervisor (authoritative student_assignments)
        cursor.execute("SELECT supervisor_id, COUNT(*) as cnt FROM student_assignments GROUP BY supervisor_id")
        counts = {}
        for r in cursor.fetchall():
            sid = r["supervisor_id"] if "supervisor_id" in r.keys() else r[0]
            cnt = r["cnt"] if "cnt" in r.keys() else r[1]
            counts[sid] = cnt

        return render_template(
            "admin/supervisors.html",
            supervisors=supervisors,
            assignment_counts=counts,
            active_page="users"
        )

    finally:
        cursor.close()
        conn.close()
         

@admin.route("/admin/supervisor/<int:supervisor_id>")
@role_required("admin")
def supervisor_profile(supervisor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, username, email, role, status FROM users WHERE id = ? AND role IN ('supervisor','pending_supervisor')", (supervisor_id,))
        supervisor = cursor.fetchone()
        if not supervisor:
            return "Supervisor not found", 404
        cursor.execute("SELECT COUNT(*) FROM student_assignments WHERE supervisor_id = ?", (supervisor_id,))
        assigned_count = cursor.fetchone()[0]
        cursor.execute("""
            SELECT u.id, u.username, u.email
            FROM users u
            JOIN student_assignments sa ON u.id = sa.student_id
            WHERE sa.supervisor_id = ?
            ORDER BY u.username
        """, (supervisor_id,))
        assigned_students = cursor.fetchall()
        return render_template(
            "admin/supervisor_profile.html",
            supervisor=supervisor,
            assigned_count=assigned_count,
            assigned_students=assigned_students,
            active_page="users"
        )
    finally:
        cursor.close()
        conn.close()

@admin.route("/admin/supervisor/edit/<int:supervisor_id>", methods=["GET", "POST"])
@role_required("admin")
def edit_supervisor(supervisor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, username, email, role, status FROM users WHERE id = ? AND role IN ('supervisor','pending_supervisor')", (supervisor_id,))
        supervisor = cursor.fetchone()
        if not supervisor:
            return "Supervisor not found", 404
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            errors = {}
            if not username or len(username) < 3 or not __import__("re").match(r"^[A-Za-z0-9_.-]+$", username):
                errors["username"] = "Username must be at least 3 chars, letters/numbers/_.-"
            if not email or not __import__("re").match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                errors["email"] = "Invalid email"
            # uniqueness
            cursor.execute("SELECT id FROM users WHERE username = ? AND id != ?", (username, supervisor_id))
            if cursor.fetchone():
                errors["username"] = "Username already exists"
            cursor.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?) AND id != ?", (email, supervisor_id))
            if cursor.fetchone():
                errors["email"] = "Email already exists"
            if errors:
                for f, m in errors.items():
                    flash(f"{f}: {m}", "danger")
                return render_template("admin/edit_supervisor.html", supervisor=supervisor)
            cursor.execute("UPDATE users SET username = ?, email = ? WHERE id = ?", (username, email, supervisor_id))
            conn.commit()
            flash("Supervisor updated successfully", "success")
            return redirect(url_for("admin.supervisor_profile", supervisor_id=supervisor_id))
        return render_template("admin/edit_supervisor.html", supervisor=supervisor)
    finally:
        cursor.close()
        conn.close()

@admin.route("/admin/supervisor/<int:supervisor_id>/deactivate", methods=["POST"])
@role_required("admin")
def deactivate_supervisor(supervisor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT username, email FROM users WHERE id = ? AND role IN ('supervisor','pending_supervisor')", (supervisor_id,))
        sup = cursor.fetchone()
        if not sup:
            flash("Supervisor not found", "danger")
            return redirect(url_for("admin.admin_supervisors"))
        cursor.execute("UPDATE users SET status = 'inactive' WHERE id = ?", (supervisor_id,))
        conn.commit()
        if sup["email"]:
            try:
                send_email(sup["email"], "Nexora Account Deactivated", f"Hello {sup['username']},\n\nYour supervisor account has been deactivated.\n\nNexora System")
            except:
                pass
        flash("Supervisor deactivated", "success")
        return redirect(url_for("admin.supervisor_profile", supervisor_id=supervisor_id))
    finally:
        cursor.close()
        conn.close()

@admin.route("/admin/supervisor/<int:supervisor_id>/activate", methods=["POST"])
@role_required("admin")
def activate_supervisor(supervisor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT username, email FROM users WHERE id = ? AND role IN ('supervisor','pending_supervisor')", (supervisor_id,))
        sup = cursor.fetchone()
        if not sup:
            flash("Supervisor not found", "danger")
            return redirect(url_for("admin.admin_supervisors"))
        cursor.execute("UPDATE users SET status = 'active' WHERE id = ?", (supervisor_id,))
        conn.commit()
        if sup["email"]:
            try:
                send_email(sup["email"], "Nexora Account Activated", f"Hello {sup['username']},\n\nYour supervisor account has been activated.\n\nNexora System")
            except:
                pass
        flash("Supervisor activated", "success")
        return redirect(url_for("admin.supervisor_profile", supervisor_id=supervisor_id))
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
    # Legacy route — canonical is /admin/internship-assign
    if request.method == "GET":
        return redirect(url_for("admin.internship_assign"), code=301)
    # Preserve POST compatibility (rare) — handle assignment then redirect to canonical
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        student_id = request.form.get("student_id")
        supervisor_id = request.form.get("supervisor_id")
        if student_id and supervisor_id:
            if using_postgres():
                cursor.execute(
                    "INSERT INTO student_assignments (student_id, supervisor_id) VALUES (?, ?) ON CONFLICT (student_id, supervisor_id) DO NOTHING",
                    (student_id, supervisor_id),
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO student_assignments (student_id, supervisor_id) VALUES (?, ?)",
                    (student_id, supervisor_id),
                )
            conn.commit()
    except Exception:
        try:
            conn.rollback()
        except:
            pass
    finally:
        conn.close()
    return redirect(url_for("admin.internship_assign"), code=302)

@admin.route("/admin/reports")
@role_required("admin")
def admin_reports_list():
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                c.id,
                c.name,
                c.section,
                COALESCE(c.archived, 0),
                COALESCE(sup.username, 'Unknown Supervisor'),
                COALESCE(cid.company_name, ''),
                COALESCE(cid.internship_title, ''),
                student.id,
                student.username,
                student.email
            FROM classrooms c
            JOIN users sup ON sup.id = c.supervisor_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            LEFT JOIN classroom_students cs ON cs.classroom_id = c.id
            LEFT JOIN users student
                ON student.id = cs.student_id
               AND student.role = 'student'
            WHERE COALESCE(c.classroom_type, 'classroom') = 'internship'
            ORDER BY COALESCE(c.archived, 0) ASC,
                     LOWER(c.name) ASC,
                     LOWER(c.section) ASC,
                     LOWER(COALESCE(student.username, '')) ASC,
                     c.id ASC
            """
        )
        rows = cursor.fetchall()

        classroom_groups = []
        groups_by_id = {}
        for row in rows:
            classroom_id = int(row[0])
            classroom = groups_by_id.get(classroom_id)
            if classroom is None:
                classroom = {
                    "id": classroom_id,
                    "name": row[1] or "Intern Classroom",
                    "section": row[2] or "",
                    "archived": bool(row[3]),
                    "supervisor_name": row[4] or "Unknown Supervisor",
                    "company_name": row[5] or "",
                    "internship_title": row[6] or "",
                    "students": [],
                }
                groups_by_id[classroom_id] = classroom
                classroom_groups.append(classroom)

            if row[7] is not None:
                classroom["students"].append(
                    {
                        "id": int(row[7]),
                        "username": row[8] or "Student",
                        "email": row[9] or "",
                    }
                )

        total_interns = sum(len(classroom["students"]) for classroom in classroom_groups)

        return render_template(
            "admin/reports_list.html",
            classroom_groups=classroom_groups,
            total_interns=total_interns,
            active_page="reports",
        )
    finally:
        cursor.close()
        conn.close()

@admin.route("/admin/reports/<int:student_id>")
@role_required("admin")
def admin_reports(student_id):
    # Legacy route — canonical is /admin/reports/student/<id>
    return redirect(url_for("admin.student_report", student_id=student_id), code=301)

@admin.route("/admin/assignments")
@role_required("admin")
def admin_assignments():

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
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

        return render_template(
            "admin/assignments.html",
            students=students,
            supervisors=supervisors,
            assignments=assignments,
            pending_users=pending_users,
            active_page="assign"
        )
    finally:
        cursor.close()
        conn.close()
    
def _approval_management_redirect(default_endpoint):
    if request.form.get("return_to") == "users":
        return redirect(url_for("admin.admin_users"))
    return redirect(url_for(default_endpoint))


@admin.route("/admin/reject-student/<int:user_id>", methods=["POST"])
@role_required("admin")
def reject_student(user_id):
    user = reject_pending_user(
        user_id,
        expected_pending_role="pending_student",
    )

    if user:
        flash("Student account request rejected.", "success")
    else:
        flash("That student account is no longer pending.", "warning")

    return _approval_management_redirect("admin.admin_students")


@admin.route("/admin/approve-student/<int:user_id>", methods=["POST"])
@role_required("admin")
def approve_student(user_id):
    user = approve_pending_user(
        user_id,
        expected_pending_role="pending_student",
        automatic=False,
    )

    if user:
        flash("Student account approved. An approval email was sent when available.", "success")
    else:
        flash("That student account is no longer pending.", "warning")

    return _approval_management_redirect("admin.admin_students")


@admin.route("/admin/reject-supervisor/<int:user_id>", methods=["POST"])
@role_required("admin")
def reject_supervisor(user_id):
    user = reject_pending_user(
        user_id,
        expected_pending_role="pending_supervisor",
    )

    if user:
        flash("Supervisor account request rejected.", "success")
    else:
        flash("That supervisor account is no longer pending.", "warning")

    return _approval_management_redirect("admin.admin_supervisors")


@admin.route("/admin/approve-supervisor/<int:user_id>", methods=["POST"])
@role_required("admin")
def approve_supervisor(user_id):
    user = approve_pending_user(
        user_id,
        expected_pending_role="pending_supervisor",
        automatic=False,
    )

    if user:
        flash("Supervisor account approved. An approval email was sent when available.", "success")
    else:
        flash("That supervisor account is no longer pending.", "warning")

    return _approval_management_redirect("admin.admin_supervisors")


@admin.route("/admin/users/bulk", methods=["POST"])
@role_required("admin")
def bulk_action():
    from flask import jsonify
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    action = (data.get("action") or "").strip().lower()
    allowed_actions = {"activate", "deactivate", "delete"}
    if action not in allowed_actions:
        return jsonify({"success": False, "error": "Invalid action"}), 400
    # Validate ids
    try:
        ids = [int(x) for x in ids]
    except:
        return jsonify({"success": False, "error": "Invalid ids"}), 400
    if not ids:
        return jsonify({"success": False, "error": "No ids provided"}), 400
    # Prevent bulk on admin accounts and limit scope
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Use transaction
        updated = 0
        for uid in ids:
            cursor.execute("SELECT role, status FROM users WHERE id = ?", (uid,))
            user = cursor.fetchone()
            if not user:
                continue
            role = user["role"] if "role" in user.keys() else user[0]
            # Never touch admin
            if role == "admin":
                continue
            # Only allow student/supervisor/pending/rejected/inactive
            if role not in ("student", "supervisor", "pending_student", "pending_supervisor", "inactive", "rejected"):
                continue
            if action == "activate":
                # For inactive status or pending/rejected, set to active/appropriate role
                if role in ("pending_student", "pending_supervisor", "rejected"):
                    # Approve pending -> map to active role
                    new_role = "student" if "student" in role else "supervisor"
                    cursor.execute("UPDATE users SET role = ?, status = 'active' WHERE id = ?", (new_role, uid))
                else:
                    cursor.execute("UPDATE users SET status = 'active' WHERE id = ?", (uid,))
                updated += cursor.rowcount
            elif action == "deactivate":
                cursor.execute("UPDATE users SET status = 'inactive' WHERE id = ?", (uid,))
                updated += cursor.rowcount
            elif action == "delete":
                # Soft delete: pending -> rejected, active -> inactive (preserve data)
                if role in ("pending_student", "pending_supervisor"):
                    cursor.execute("UPDATE users SET role = 'rejected' WHERE id = ?", (uid,))
                else:
                    cursor.execute("UPDATE users SET status = 'inactive' WHERE id = ?", (uid,))
                updated += cursor.rowcount
        conn.commit()
        return jsonify({"success": True, "updated_count": updated})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@admin.route("/admin/internship-assign", methods=["GET", "POST"])
@role_required("admin")
def internship_assign():
    """Assign or transfer a student to an active Supervisor-owned Intern Classroom."""
    conn = get_db_connection()
    cursor = conn.cursor()

    def row_value(row, key, index=0, default=None):
        if row is None:
            return default
        try:
            if key in row.keys():
                value = row[key]
                return default if value is None else value
        except (AttributeError, KeyError, TypeError):
            pass
        try:
            value = row[index]
            return default if value is None else value
        except (IndexError, KeyError, TypeError):
            return default

    def get_active_membership(student_id):
        return cursor.execute(
            """
            SELECT
                c.id AS classroom_id,
                c.name AS classroom_name,
                c.supervisor_id,
                COALESCE(s.username, '') AS supervisor_name,
                COALESCE(cid.company_name, '') AS company_name
            FROM classroom_students cs
            JOIN classrooms c ON c.id = cs.classroom_id
            LEFT JOIN users s ON s.id = c.supervisor_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE cs.student_id = ?
              AND COALESCE(c.classroom_type, 'classroom') = 'internship'
              AND COALESCE(c.archived, 0) = 0
            ORDER BY cs.id DESC
            LIMIT 1
            """,
            (student_id,),
        ).fetchone()

    def get_target_placement(classroom_id):
        return cursor.execute(
            """
            SELECT
                c.id AS classroom_id,
                c.name AS classroom_name,
                COALESCE(c.section, '') AS section,
                COALESCE(c.code, '') AS code,
                c.supervisor_id,
                supervisor.username AS supervisor_name,
                COALESCE(supervisor.email, '') AS supervisor_email,
                COALESCE(cid.company_name, '') AS company_name,
                COALESCE(cid.internship_title, '') AS internship_title,
                COALESCE(cid.industry, '') AS industry,
                COALESCE(cid.work_arrangement, '') AS work_arrangement,
                COALESCE(cid.compensation, '') AS compensation,
                COALESCE(cid.location, '') AS location,
                COALESCE(cid.start_date, '') AS start_date,
                COALESCE(cid.end_date, '') AS end_date,
                COALESCE(cid.enrollment_deadline, '') AS enrollment_deadline,
                COALESCE(cid.required_hours, 0) AS required_hours,
                COALESCE(cid.company_website, '') AS company_website
            FROM classrooms c
            JOIN users supervisor ON supervisor.id = c.supervisor_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.id = ?
              AND COALESCE(c.classroom_type, 'classroom') = 'internship'
              AND COALESCE(c.archived, 0) = 0
              AND supervisor.role = 'supervisor'
              AND COALESCE(supervisor.status, 'active') = 'active'
            LIMIT 1
            """,
            (classroom_id,),
        ).fetchone()

    try:
        if request.method == "POST":
            student_id_raw = (request.form.get("student_id") or "").strip()
            classroom_id_raw = (request.form.get("classroom_id") or "").strip()
            confirm_transfer = (request.form.get("confirm_transfer") or "") == "1"
            errors = []

            try:
                student_id = int(student_id_raw)
            except (TypeError, ValueError):
                student_id = 0
                errors.append("Student is required")

            try:
                classroom_id = int(classroom_id_raw)
            except (TypeError, ValueError):
                classroom_id = 0
                errors.append("Available Supervisor is required")

            student_row = None
            placement_row = None
            current_membership = None

            if student_id:
                student_row = cursor.execute(
                    """
                    SELECT id, username
                    FROM users
                    WHERE id = ?
                      AND role = 'student'
                      AND COALESCE(status, 'active') = 'active'
                    LIMIT 1
                    """,
                    (student_id,),
                ).fetchone()
                if not student_row:
                    errors.append("Selected student is not available")
                else:
                    current_membership = get_active_membership(student_id)

            if classroom_id:
                placement_row = get_target_placement(classroom_id)
                if not placement_row:
                    errors.append("Selected Supervisor / Intern Classroom is no longer available")

            transfer_required = False
            if not errors and current_membership and placement_row:
                current_classroom_id = int(row_value(current_membership, "classroom_id", 0, 0) or 0)
                if current_classroom_id == classroom_id:
                    errors.append(
                        f"Student is already assigned to {row_value(current_membership, 'classroom_name', 1, 'this Intern Classroom')}."
                    )
                else:
                    transfer_required = True
                    if not confirm_transfer:
                        errors.append(
                            "This student already has an active Intern Classroom. Confirm the transfer to remove the current placement and assign the new one."
                        )

            if transfer_required and confirm_transfer and not errors:
                open_attendance = cursor.execute(
                    """
                    SELECT id
                    FROM attendance
                    WHERE student_id = ? AND status = 'Open'
                    LIMIT 1
                    """,
                    (student_id,),
                ).fetchone()
                if open_attendance:
                    errors.append("Student must Clock Out before being transferred to another Intern Classroom.")

            if errors:
                flash("; ".join(errors), "danger")
            else:
                supervisor_id = int(row_value(placement_row, "supervisor_id", 4, 0) or 0)
                supervisor_name = str(row_value(placement_row, "supervisor_name", 5, "") or "")
                supervisor_email = str(row_value(placement_row, "supervisor_email", 6, "") or "")
                classroom_name = str(row_value(placement_row, "classroom_name", 1, "Intern Classroom") or "Intern Classroom")
                company_name = str(row_value(placement_row, "company_name", 7, "") or "").strip() or classroom_name
                company_address = str(row_value(placement_row, "location", 12, "") or "").strip()
                position = str(row_value(placement_row, "internship_title", 8, "") or "").strip() or classroom_name
                start_date = str(row_value(placement_row, "start_date", 13, "") or "")
                end_date = str(row_value(placement_row, "end_date", 14, "") or "")
                required_hours = int(row_value(placement_row, "required_hours", 16, 0) or 0) or 486
                student_name = str(row_value(student_row, "username", 1, "Student") or "Student")

                old_classroom_id = None
                old_classroom_name = None
                old_supervisor_id = None
                old_supervisor_name = None

                try:
                    if current_membership:
                        old_classroom_id = int(row_value(current_membership, "classroom_id", 0, 0) or 0)
                        old_classroom_name = str(row_value(current_membership, "classroom_name", 1, "Intern Classroom") or "Intern Classroom")
                        old_supervisor_id = int(row_value(current_membership, "supervisor_id", 2, 0) or 0)
                        old_supervisor_name = str(row_value(current_membership, "supervisor_name", 3, "Supervisor") or "Supervisor")

                        cursor.execute(
                            "DELETE FROM classroom_students WHERE classroom_id = ? AND student_id = ?",
                            (old_classroom_id, student_id),
                        )
                        cursor.execute(
                            "UPDATE internships SET status = 'Transferred' WHERE student_id = ? AND status = 'Active'",
                            (student_id,),
                        )
                        if old_supervisor_id:
                            cursor.execute(
                                "DELETE FROM student_assignments WHERE student_id = ? AND supervisor_id = ?",
                                (student_id, old_supervisor_id),
                            )

                    cursor.execute(
                        """
                        INSERT INTO internships
                        (
                            student_id,
                            company_name,
                            company_address,
                            supervisor_name,
                            supervisor_email,
                            supervisor_id,
                            position,
                            start_date,
                            end_date,
                            required_hours,
                            completed_hours,
                            status
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            student_id,
                            company_name,
                            company_address,
                            supervisor_name,
                            supervisor_email,
                            supervisor_id,
                            position,
                            start_date,
                            end_date,
                            required_hours,
                            0,
                            "Active",
                        ),
                    )

                    cursor.execute(
                        "INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)",
                        (classroom_id, student_id),
                    )

                    if using_postgres():
                        cursor.execute(
                            """
                            INSERT INTO student_assignments (student_id, supervisor_id)
                            VALUES (?, ?)
                            ON CONFLICT (student_id, supervisor_id) DO NOTHING
                            """,
                            (student_id, supervisor_id),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO student_assignments (student_id, supervisor_id)
                            VALUES (?, ?)
                            """,
                            (student_id, supervisor_id),
                        )

                    conn.commit()

                    # Notifications are intentionally after the placement transaction.
                    try:
                        if old_classroom_id:
                            create_notification(
                                student_id,
                                "Internship Classroom Changed",
                                f"Your internship placement was moved from {old_classroom_name} to {classroom_name}.",
                                "classroom",
                                link_url=f"/student/classes/{classroom_id}",
                            )
                            if old_supervisor_id:
                                if old_supervisor_id == supervisor_id:
                                    create_notification(
                                        old_supervisor_id,
                                        "Intern Transferred Between Classrooms",
                                        f"{student_name} was moved from {old_classroom_name} to {classroom_name} by the Administrator.",
                                        "classroom",
                                        link_url=f"/supervisor/classes/{classroom_id}",
                                    )
                                else:
                                    create_notification(
                                        old_supervisor_id,
                                        "Intern Removed / Transferred",
                                        f"{student_name} was removed from {old_classroom_name} and transferred to another Intern Classroom by the Administrator.",
                                        "classroom",
                                        link_url=f"/supervisor/classes/{old_classroom_id}",
                                    )
                                    create_notification(
                                        supervisor_id,
                                        "New Intern Assigned",
                                        f"{student_name} was transferred to your Intern Classroom {classroom_name} by the Administrator.",
                                        "classroom",
                                        link_url=f"/supervisor/classes/{classroom_id}",
                                    )
                        else:
                            create_notification(
                                student_id,
                                "Internship Classroom Assigned",
                                f"You have been assigned to {classroom_name} under {supervisor_name}.",
                                "classroom",
                                link_url=f"/student/classes/{classroom_id}",
                            )
                            create_notification(
                                supervisor_id,
                                "New Intern Assigned",
                                f"{student_name} was assigned to your Intern Classroom {classroom_name} by the Administrator.",
                                "classroom",
                                link_url=f"/supervisor/classes/{classroom_id}",
                            )
                    except Exception:
                        current_app.logger.warning(
                            "Admin internship assignment notification failed",
                            exc_info=True,
                        )

                    if old_classroom_id:
                        flash(
                            f"{student_name} moved from {old_classroom_name} to {classroom_name} successfully.",
                            "success",
                        )
                    else:
                        flash(
                            f"{student_name} has been assigned to {classroom_name} successfully.",
                            "success",
                        )
                    return redirect(url_for("admin.internship_assign"))
                except Exception as exc:
                    conn.rollback()
                    current_app.logger.exception("Admin internship assignment failed")
                    flash(f"Failed to assign internship: {exc}", "danger")

        student_rows = cursor.execute(
            """
            SELECT id, username
            FROM users
            WHERE role = 'student'
              AND COALESCE(status, 'active') = 'active'
            ORDER BY LOWER(username), id
            """
        ).fetchall()

        students = []
        for row in student_rows:
            student_id = int(row_value(row, "id", 0, 0) or 0)
            membership = get_active_membership(student_id)
            students.append(
                {
                    "id": student_id,
                    "username": str(row_value(row, "username", 1, "") or ""),
                    "current_classroom_id": int(row_value(membership, "classroom_id", 0, 0) or 0) if membership else 0,
                    "current_classroom_name": str(row_value(membership, "classroom_name", 1, "") or "") if membership else "",
                    "current_supervisor_id": int(row_value(membership, "supervisor_id", 2, 0) or 0) if membership else 0,
                    "current_supervisor_name": str(row_value(membership, "supervisor_name", 3, "") or "") if membership else "",
                    "current_company_name": str(row_value(membership, "company_name", 4, "") or "") if membership else "",
                }
            )

        placement_rows = cursor.execute(
            """
            SELECT
                c.id AS classroom_id,
                c.name AS classroom_name,
                COALESCE(c.section, '') AS section,
                COALESCE(c.code, '') AS code,
                c.supervisor_id,
                supervisor.username AS supervisor_name,
                COALESCE(supervisor.email, '') AS supervisor_email,
                COALESCE(cid.company_name, '') AS company_name,
                COALESCE(cid.internship_title, '') AS internship_title,
                COALESCE(cid.industry, '') AS industry,
                COALESCE(cid.work_arrangement, '') AS work_arrangement,
                COALESCE(cid.compensation, '') AS compensation,
                COALESCE(cid.location, '') AS location,
                COALESCE(cid.start_date, '') AS start_date,
                COALESCE(cid.end_date, '') AS end_date,
                COALESCE(cid.enrollment_deadline, '') AS enrollment_deadline,
                COALESCE(cid.required_hours, 0) AS required_hours,
                COALESCE(cid.company_website, '') AS company_website,
                (
                    SELECT COUNT(*)
                    FROM classroom_students cs
                    WHERE cs.classroom_id = c.id
                ) AS student_count
            FROM classrooms c
            JOIN users supervisor ON supervisor.id = c.supervisor_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE COALESCE(c.classroom_type, 'classroom') = 'internship'
              AND COALESCE(c.archived, 0) = 0
              AND supervisor.role = 'supervisor'
              AND COALESCE(supervisor.status, 'active') = 'active'
            ORDER BY LOWER(supervisor.username), LOWER(c.name), c.id
            """
        ).fetchall()

        placements = []
        for row in placement_rows:
            placements.append(
                {
                    "classroom_id": int(row_value(row, "classroom_id", 0, 0) or 0),
                    "classroom_name": str(row_value(row, "classroom_name", 1, "") or ""),
                    "section": str(row_value(row, "section", 2, "") or ""),
                    "code": str(row_value(row, "code", 3, "") or ""),
                    "supervisor_id": int(row_value(row, "supervisor_id", 4, 0) or 0),
                    "supervisor_name": str(row_value(row, "supervisor_name", 5, "") or ""),
                    "supervisor_email": str(row_value(row, "supervisor_email", 6, "") or ""),
                    "company_name": str(row_value(row, "company_name", 7, "") or ""),
                    "internship_title": str(row_value(row, "internship_title", 8, "") or ""),
                    "industry": str(row_value(row, "industry", 9, "") or ""),
                    "work_arrangement": str(row_value(row, "work_arrangement", 10, "") or ""),
                    "compensation": str(row_value(row, "compensation", 11, "") or ""),
                    "location": str(row_value(row, "location", 12, "") or ""),
                    "start_date": str(row_value(row, "start_date", 13, "") or ""),
                    "end_date": str(row_value(row, "end_date", 14, "") or ""),
                    "enrollment_deadline": str(row_value(row, "enrollment_deadline", 15, "") or ""),
                    "required_hours": int(row_value(row, "required_hours", 16, 0) or 0),
                    "company_website": str(row_value(row, "company_website", 17, "") or ""),
                    "student_count": int(row_value(row, "student_count", 18, 0) or 0),
                }
            )

        return render_template(
            "admin/internship_assign.html",
            students=students,
            placements=placements,
            active_page="internship",
        )
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        conn.close()


@admin.route('/admin/assign-role', methods=['POST'])
@role_required("admin")
def assign_role():
    # Only allow student/supervisor transitions for pending users, prevent admin escalation
    allowed_roles = {"student", "supervisor"}
    user_id = request.form.get("user_id", "").strip()
    new_role = request.form.get("role", "").strip()
    if new_role not in allowed_roles:
        flash("Invalid role assignment", "danger")
        return redirect("/admin/assignments")
    if not user_id or not user_id.isdigit():
        flash("Invalid user", "danger")
        return redirect("/admin/assignments")
    conn = get_db_connection()
    cursor = conn.cursor()
    # Verify user is pending before allowing transition
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        flash("User not found", "danger")
        return redirect("/admin/assignments")
    current_role = row["role"] if "role" in row.keys() else row[0]
    if current_role not in ("pending_student", "pending_supervisor"):
        cursor.close()
        conn.close()
        flash("Only pending users can be assigned via this action", "danger")
        return redirect("/admin/assignments")

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
        AND LOWER(username) LIKE LOWER(?)
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
        AND LOWER(users.username) LIKE LOWER(?)

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


    # ATTENDANCE PAGINATION & METRICS

    attendance_per_page = 10

    attendance_page = request.args.get(
        "attendance_page",
        1,
        type=int
    )

    if attendance_page < 1:
        attendance_page = 1

    total_sessions_row = conn.execute("""
        SELECT COUNT(*) FROM attendance WHERE student_id = ?
    """, (student_id,)).fetchone()
    total_sessions = total_sessions_row[0] if total_sessions_row else 0

    total_hours_row = conn.execute("""
        SELECT COALESCE(SUM(hours_rendered), 0) FROM attendance WHERE student_id = ?
    """, (student_id,)).fetchone()
    total_hours = total_hours_row[0] if total_hours_row else 0

    attendance_total_pages = (
        (total_sessions + attendance_per_page - 1)
        // attendance_per_page
    )

    if attendance_total_pages > 0 and attendance_page > attendance_total_pages:
        attendance_page = attendance_total_pages

    attendance_start = (
        attendance_page - 1
    ) * attendance_per_page

    attendance_raw = conn.execute("""
        SELECT
            id,
            clock_in,
            clock_out,
            hours_rendered,
            status
        FROM attendance
        WHERE student_id = ?
        ORDER BY clock_in DESC
        LIMIT ? OFFSET ?
    """, (student_id, attendance_per_page, attendance_start)).fetchall()

    attendance_display = [
    (
        session[0],
        format_date(session[1]),
        format_time(session[1]),
        format_time(session[2]),
        session[3],
        session[4]
    )
    for session in attendance_raw
]

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

        parsed_log_date = parse_datetime(log[0])
        if not parsed_log_date:
            continue

        date_value = parsed_log_date.strftime("%Y-%m-%d")
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


    # Evaluations/Feedback with ML section — uses stored ML fields with legacy fallback
    # Prefer stored ML fields; recompute only for legacy NULLs.
    try:
        raw_feedback = conn.execute("""
            SELECT
                feedback.comment,
                feedback.created_at,
                feedback.performance_label,
                users.username,
                feedback.ml_prediction,
                feedback.ml_sentiment,
                feedback.ml_competency,
                feedback.ml_recommendation,
                feedback.ml_svm_prediction,
                feedback.ml_confidence
            FROM feedback
            JOIN users ON feedback.supervisor_id = users.id
            WHERE feedback.student_id = ?
            ORDER BY feedback.created_at DESC
        """, (student_id,)).fetchall()
        has_ml_cols = True
    except Exception:
        # Legacy DB without ML columns — fallback to 4-col query
        raw_feedback = conn.execute("""
            SELECT
                feedback.comment,
                feedback.created_at,
                feedback.performance_label,
                users.username
            FROM feedback
            JOIN users ON feedback.supervisor_id = users.id
            WHERE feedback.student_id = ?
            ORDER BY feedback.created_at DESC
        """, (student_id,)).fetchall()
        has_ml_cols = False

    # Build enriched feedback list and ML collections
    feedback = []
    ml_predictions = []
    sentiments = []
    competencies = []
    recommendations_list = []
    confidences = []
    nb_preds = []
    svm_preds = []

    for fb in raw_feedback:
        comment = fb[0]
        created_raw = fb[1]
        human_label = fb[2]
        supervisor_name = fb[3]
        # stored ML (may be None for legacy)
        if has_ml_cols:
            try:
                stored_pred = fb[4] if len(fb) > 4 else None
                stored_sent = fb[5] if len(fb) > 5 else None
                stored_comp = fb[6] if len(fb) > 6 else None
                stored_rec = fb[7] if len(fb) > 7 else None
                stored_svm = fb[8] if len(fb) > 8 else None
                stored_conf = fb[9] if len(fb) > 9 else None
                # HybridRow supports keys
                try:
                    if "ml_prediction" in fb.keys():
                        stored_pred = fb["ml_prediction"]
                        stored_sent = fb["ml_sentiment"]
                        stored_comp = fb["ml_competency"]
                        stored_rec = fb["ml_recommendation"]
                        stored_svm = fb["ml_svm_prediction"]
                        stored_conf = fb["ml_confidence"]
                except Exception:
                    pass
            except Exception:
                stored_pred = stored_sent = stored_comp = stored_rec = stored_svm = stored_conf = None
        else:
            stored_pred = stored_sent = stored_comp = stored_rec = stored_svm = stored_conf = None

        # Fallback for NULL/empty stored values using predictor (no DB write)
        needs_fallback = not stored_pred or not stored_sent
        if needs_fallback:
            try:
                d = analyze_feedback_detailed(comment)
                if not stored_pred:
                    stored_pred = d.get("performance_label")
                if not stored_sent:
                    stored_sent = d.get("sentiment")
                if not stored_comp:
                    stored_comp = d.get("competency")
                if not stored_rec:
                    stored_rec = d.get("recommendation")
                if not stored_svm:
                    stored_svm = d.get("svm_prediction")
                if stored_conf is None:
                    stored_conf = d.get("confidence", 0.0)
            except Exception:
                if not stored_pred:
                    try:
                        stored_pred = analyze_feedback(comment)
                    except Exception:
                        stored_pred = human_label or "Satisfactory"
                if not stored_sent:
                    stored_sent = "Neutral"
                if not stored_comp:
                    stored_comp = "Adequate Competency"
                if not stored_rec:
                    stored_rec = "Continue monitoring performance."
                if not stored_svm:
                    stored_svm = stored_pred
                if stored_conf is None:
                    stored_conf = 0.0
        # Normalise confidence
        try:
            stored_conf = float(stored_conf) if stored_conf is not None else 0.0
        except Exception:
            stored_conf = 0.0

        # Keep backward-compatible tuple: (comment, formatted_date, human_label, supervisor, ml_pred, ml_sent, ml_comp, ml_rec, ml_svm, ml_conf)
        feedback.append((
            comment,
            format_datetime(created_raw),
            human_label,
            supervisor_name,
            stored_pred,
            stored_sent,
            stored_comp,
            stored_rec,
            stored_svm,
            stored_conf,
        ))
        if stored_pred:
            ml_predictions.append(stored_pred)
            nb_preds.append(stored_pred)
        if stored_sent:
            sentiments.append(stored_sent)
        if stored_comp:
            competencies.append(stored_comp)
        if stored_rec:
            recommendations_list.append(stored_rec)
        confidences.append(stored_conf)
        if stored_svm:
            svm_preds.append(stored_svm)

    total_feedback = len(feedback)

    # ML CLASSIFICATION SUMMARY

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

    # --- Phase 8 extended ML analysis (for template) ---
    # Sentiment distribution
    sentiment_labels = ["Positive", "Neutral", "Negative"]
    sentiment_counts = Counter(sentiments)
    sentiment_distribution = [
        {"label": s, "count": sentiment_counts.get(s, 0)} for s in sentiment_labels
    ]

    # Competency distribution
    competency_labels = [
        "Outstanding Competency",
        "Strong Competency",
        "Adequate Competency",
        "Developing Competency",
        "Needs Significant Development",
    ]
    competency_counts = Counter(competencies)
    competency_distribution = [
        {"label": c, "count": competency_counts.get(c, 0)} for c in competency_labels if competency_counts.get(c, 0) > 0
    ]
    # If no competency yet, keep all zero for transparency
    if not competency_distribution and not ml_predictions:
        competency_distribution = [{"label": c, "count": 0} for c in competency_labels]

    # Recommendation summary — unique aggregated
    recommendation_summary = []
    seen_recs = set()
    for r in recommendations_list:
        if r not in seen_recs:
            seen_recs.add(r)
            recommendation_summary.append(r)

    # Average confidence (handle NULLs → already 0.0)
    try:
        average_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    except Exception:
        average_confidence = 0.0

    # Model comparison: NB vs SVM distributions
    nb_counts = Counter(nb_preds)
    svm_counts = Counter(svm_preds)
    model_comparison = {
        "nb_distribution": [{"label": c, "count": nb_counts.get(c, 0)} for c in ml_categories],
        "svm_distribution": [{"label": c, "count": svm_counts.get(c, 0)} for c in ml_categories],
        "agreement_rate": None,
    }
    if nb_preds and svm_preds and len(nb_preds) == len(svm_preds):
        try:
            agree = sum(1 for a, b in zip(nb_preds, svm_preds) if a == b)
            model_comparison["agreement_rate"] = round(agree / len(nb_preds), 3)
        except Exception:
            pass

    ml_analysis = {
        "performance_distribution": ml_distribution,
        "sentiment_distribution": sentiment_distribution,
        "competency_distribution": competency_distribution,
        "recommendations": recommendation_summary,
        "average_confidence": average_confidence,
        "model_comparison": model_comparison,
        "total_feedback": total_feedback,
    }


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
        ml_analysis=ml_analysis,
        sentiment_distribution=sentiment_distribution,
        competency_distribution=competency_distribution,
        recommendation_summary=recommendation_summary,
        average_confidence=average_confidence,
        model_comparison=model_comparison,

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

    # Use a half-open range [report_date, next_day) instead of
    # SQLite-only date() so the query is portable across SQLite and
    # PostgreSQL, and can still use an index on the timestamp column.

    next_day = report_date + timedelta(days=1)


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
        AND clock_in >= ?
        AND clock_in < ?
        ORDER BY clock_in ASC
    """, (student_id, report_date, next_day)).fetchall()


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
        AND created_at >= ?
        AND created_at < ?
        ORDER BY created_at ASC
    """, (student_id, report_date, next_day)).fetchall()


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
    methods=["POST"]
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
            AND role = 'student'
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
            AND role = 'student'
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
    methods=["POST"]
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
            AND role = 'student'
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
            AND role = 'student'
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