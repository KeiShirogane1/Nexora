from flask import Blueprint, render_template, session, request, redirect, url_for, flash
from app.Http.Middleware.security import role_required
from app.Services.email_service import (
    send_email,
    send_profile_updated_email
)
from app.Services.profile_service import (
    update_student_profile,
    get_student_profile_data
)
from app.Services.profile_history_service import (
    log_profile_change,
    get_profile_history
)

from app.Services.notification_service import (
    create_notification
)
import os
from app.Models.db import get_db_connection, using_postgres
from datetime import datetime
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
            SELECT DISTINCT
                users.id,
                users.username,
                users.email,
                users.role,
                student_profiles.major_program,
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

        students = cursor.fetchall()


        # Fetch real supervisors and programs for modal dropdowns (no fake data)
        cursor.execute("SELECT id, username FROM users WHERE role='supervisor' ORDER BY username")
        supervisors_list = cursor.fetchall()
        cursor.execute("SELECT DISTINCT major_program FROM student_profiles WHERE major_program IS NOT NULL AND major_program != ''")
        programs_raw = [r[0] for r in cursor.fetchall() if r[0]]
        # Use real values plus common defaults, deduplicated
        programs = sorted(set(programs_raw + ["BSIT", "BS Information Technology", "BSCS"]), key=lambda x: x.lower())

        return render_template(
            "admin/students.html",
            students=students,
            supervisors_list=supervisors_list,
            programs=programs,
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
    program = (data.get("program") or "").strip()
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
    # Legacy route — canonical is /admin/reports/student/<id>
    return redirect(url_for("admin.student_report", student_id=student_id), code=301)

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
    
@admin.route("/admin/reject-student/<int:user_id>", methods=["POST"])
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
    
@admin.route("/admin/approve-student/<int:user_id>", methods=["POST"])
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


@admin.route("/admin/reject-supervisor/<int:user_id>", methods=["POST"])
@role_required("admin")
def reject_supervisor(user_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT username, email
            FROM users
            WHERE id = ?
            AND role = 'pending_supervisor'
            """,
            (user_id,)
        )

        user = cursor.fetchone()


        if not user:
            return redirect(
                "/admin/users/supervisors"
            )


        cursor.execute(
            """
            UPDATE users
            SET role = 'rejected'
            WHERE id = ?
            AND role = 'pending_supervisor'
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

Your Nexora supervisor account request was not approved.

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
        "/admin/users/supervisors"
    )


@admin.route("/admin/approve-supervisor/<int:user_id>", methods=["POST"])
@role_required("admin")
def approve_supervisor(user_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT username, email
            FROM users
            WHERE id = ?
            AND role = 'pending_supervisor'
            """,
            (user_id,)
        )

        user = cursor.fetchone()


        if not user:
            return redirect(
                "/admin/users/supervisors"
            )


        cursor.execute(
            """
            UPDATE users
            SET role = 'supervisor'
            WHERE id = ?
            AND role = 'pending_supervisor'
            """,
            (user_id,)
        )

        conn.commit()


        if user["email"]:

            try:

                send_email(
                    user["email"],
                    "Nexora Account Approved",
                    f"""
                    Hello {user["username"]},

                    Your Nexora supervisor account has been approved.

                    You may now login to the Nexora system.

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
        "/admin/users/supervisors"
    )


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

    conn = get_db_connection()
    cursor = conn.cursor()

    # For GET, load students and supervisors for form
    if request.method == "POST":
        try:
            student_id = request.form.get("student_id", "").strip()
            company_name = request.form.get("company_name", "").strip()
            company_address = request.form.get("company_address", "").strip()
            supervisor_name = request.form.get("supervisor_name", "").strip()
            supervisor_email = request.form.get("supervisor_email", "").strip().lower()
            supervisor_id_raw = request.form.get("supervisor_id", "").strip()
            position = request.form.get("position", "").strip()
            start_date = request.form.get("start_date", "").strip()
            end_date = request.form.get("end_date", "").strip()
            required_hours_raw = request.form.get("required_hours", "").strip()

            # Validation
            errors = []
            if not student_id:
                errors.append("Student is required")
            if not company_name:
                errors.append("Company name is required")
            if not position:
                errors.append("Position is required")
            if not start_date or not end_date:
                errors.append("Start and end date required")
            if start_date and end_date and start_date > end_date:
                errors.append("Start date must be before end date")
            try:
                required_hours = int(required_hours_raw) if required_hours_raw else 486
                if required_hours <= 0 or required_hours > 2000:
                    errors.append("Required hours must be 1-2000")
            except:
                errors.append("Required hours must be a number")
                required_hours = 486

            if errors:
                flash("; ".join(errors), "danger")
                # fall through to render with students/supervisors
            else:
                # Verify student exists and is student
                cursor.execute("SELECT id FROM users WHERE id = ? AND role = 'student'", (student_id,))
                if not cursor.fetchone():
                    flash("Selected student not found or not a student", "danger")
                else:
                    # Resolve supervisor_id — prefer explicit select, fallback to email lookup
                    supervisor_id = None
                    if supervisor_id_raw:
                        try:
                            sid = int(supervisor_id_raw)
                            cursor.execute("SELECT id FROM users WHERE id = ? AND role = 'supervisor'", (sid,))
                            if cursor.fetchone():
                                supervisor_id = sid
                                # Fill legacy name/email from supervisor record if not provided
                                if not supervisor_name or not supervisor_email:
                                    cursor.execute("SELECT username, email FROM users WHERE id = ?", (sid,))
                                    sup = cursor.fetchone()
                                    if sup:
                                        if not supervisor_name:
                                            supervisor_name = sup["username"] if "username" in sup.keys() else sup[0]
                                        if not supervisor_email:
                                            supervisor_email = sup["email"] if "email" in sup.keys() else sup[1]
                            else:
                                flash("Selected supervisor not found", "danger")
                                supervisor_id = None
                        except:
                            flash("Invalid supervisor", "danger")
                    elif supervisor_email:
                        cursor.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?) AND role='supervisor'", (supervisor_email,))
                        r = cursor.fetchone()
                        if r:
                            supervisor_id = r["id"] if "id" in r.keys() else r[0]

                    # Prevent duplicate active internship for same student (application-level)
                    cursor.execute("SELECT id FROM internships WHERE student_id = ? AND status = 'Active'", (student_id,))
                    if cursor.fetchone():
                        flash("Student already has an active internship", "danger")
                    else:
                        # ONE TRANSACTION: internship + supervisor_id + student_assignments
                        try:
                            cursor.execute("""
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
                                VALUES
                                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                                "Active"
                            ))
                            # Create student_assignments if supervisor resolved
                            if supervisor_id:
                                if using_postgres():
                                    cursor.execute(
                                        "INSERT INTO student_assignments (student_id, supervisor_id) VALUES (?, ?) ON CONFLICT (student_id, supervisor_id) DO NOTHING",
                                        (student_id, supervisor_id)
                                    )
                                else:
                                    cursor.execute(
                                        "INSERT OR IGNORE INTO student_assignments (student_id, supervisor_id) VALUES (?, ?)",
                                        (student_id, supervisor_id)
                                    )
                            conn.commit()
                            flash("Internship assigned successfully", "success")
                        except Exception as e:
                            conn.rollback()
                            flash(f"Failed to assign internship: {e}", "danger")
        except Exception as e:
            try:
                conn.rollback()
            except:
                pass
            flash(f"Assignment error: {e}", "danger")

    # Load dropdowns for form
    cursor.execute("""
        SELECT id, username
        FROM users
        WHERE role='student'
        ORDER BY username
    """)
    students = cursor.fetchall()
    cursor.execute("SELECT id, username FROM users WHERE role='supervisor' ORDER BY username")
    supervisors = cursor.fetchall()

    conn.close()

    return render_template(
        "admin/internship_assign.html",
        students=students,
        supervisors=supervisors,
        active_page="internship"
    )    


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

        date_value = parse_datetime(log[0]).strftime("%Y-%m-%d")
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