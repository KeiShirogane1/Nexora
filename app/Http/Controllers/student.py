from flask import Blueprint, current_app, render_template, request, redirect, session, send_file, flash
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection

from app.Services.profile_service import (
    update_student_profile,
    get_student_profile_data
)
from app.Services.notification_service import create_notification

import os
import mimetypes
from werkzeug.utils import secure_filename
from datetime import datetime

# Upload hardening — allowed extensions and MIME types
ALLOWED_DOC_EXTENSIONS = {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "txt", "zip", "png", "jpg", "jpeg", "gif"}
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
MAX_IMAGE_SIZE = 2 * 1024 * 1024  # 2MB for profile pictures

def _allowed_file(filename, allowed_set):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set

def _is_safe_path(base, target):
    # Prevent path traversal — ensure target is within base
    try:
        base_abs = os.path.abspath(base)
        target_abs = os.path.abspath(target)
        return os.path.commonpath([base_abs]) == os.path.commonpath([base_abs, target_abs])
    except:
        return False

def get_student_profile():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            first_name,
            middle_name,
            last_name,
            age,
            student_id,
            profile_picture,
            phone_number,
            home_address,
            grade_year,
            major_program

        FROM student_profiles

        WHERE user_id = ?

    """,
    (
        session["user_id"],
    ))

    profile = cursor.fetchone()

    conn.close()

    return profile


def format_title_case(value):

    lowercase_words = {
        "of",
        "in",
        "and",
        "for",
        "to"
    }

    words = value.lower().split()

    formatted = []

    for word in words:

        if word in lowercase_words:
            formatted.append(word)

        else:
            formatted.append(
                word.capitalize()
            )

    return " ".join(formatted)


def parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    return datetime.fromisoformat(value)


def format_time(timestamp):
    dt = parse_datetime(timestamp)

    if not dt:
        return None

    return dt.strftime("%I:%M %p").lstrip("0")


student = Blueprint("student", __name__)

@student.before_request
def _check_student_active():
    if "user_id" in session and session.get("role") == "student":
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT status FROM users WHERE id = ?", (session.get("user_id"),)).fetchone()
            if row is not None:
                status = None
                try:
                    status = row["status"]
                except:
                    try:
                        status = row[0]
                    except:
                        status = None
                if status == "inactive":
                    return "Account deactivated — contact administrator.", 403
        finally:
            conn.close()

@student.route("/student/dashboard")
@role_required("student")
def student_dashboard():

    conn = get_db_connection()
    cursor = conn.cursor()
    
    student_user_id = int(session["user_id"])

    # =========================
    # STUDENT PROFILE
    # =========================

    cursor.execute("""
        SELECT
            first_name,
            middle_name,
            last_name,
            age,
            student_id,
            profile_picture,
            phone_number,
            home_address,
            grade_year,
            major_program

        FROM student_profiles

        WHERE user_id = ?

    """,
    (
        session["user_id"],
    ))


    profile = cursor.fetchone()

   # ==============================
    # GET STUDENT INTERNSHIP
    # ==============================

    cursor.execute("""
        SELECT
            i.company_name,
            i.position,
            i.supervisor_name,
            i.start_date,
            i.end_date,
            i.required_hours,
            i.completed_hours,
            i.status

        FROM internships i

        JOIN users u
        ON i.student_id = u.id

        WHERE u.id = ?

    """,
    (
        session["user_id"],
    ))


    internship = cursor.fetchone()

    if not profile or profile[8] is None:

        conn.close()

        return redirect(
            "/student/profile/setup"
        )



    # =========================
    # DASHBOARD STATISTICS
    # =========================


    # Total logs

    cursor.execute("""
        SELECT COUNT(*)
        FROM logs
        WHERE student_id = ?
    """,
    (
        session["user_id"],
    ))

    log_count = cursor.fetchone()[0]



    # Total tasks

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE student_id = ?
    """,
    (
        session["user_id"],
    ))

    task_total = cursor.fetchone()[0]



    # Completed tasks

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE student_id = ?
        AND status = 'Submitted'
    """,
    (
        session["user_id"],
    ))

    task_completed = cursor.fetchone()[0]



    # Documents

    cursor.execute("""
        SELECT COUNT(*)
        FROM documents
        WHERE student_id = ?
    """,
    (
        session["user_id"],
    ))

    document_count = cursor.fetchone()[0]



    # Attendance

    cursor.execute("""
        SELECT COUNT(*)
        FROM attendance
        WHERE student_id = ?
    """,
    (
        session["user_id"],
    ))

    attendance_count = cursor.fetchone()[0]



    conn.close()


    # ==========================
    # RECENT ACTIVITY
    # ==========================


    conn = get_db_connection()
    cursor = conn.cursor()



    recent_logs = cursor.execute(
        """
        SELECT *
        FROM logs
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            session["user_id"],
        )
    ).fetchall()



    recent_tasks = cursor.execute(
        """
        SELECT *
        FROM tasks
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            session["user_id"],
        )
    ).fetchall()



    recent_documents = cursor.execute(
        """
        SELECT *
        FROM documents
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            session["user_id"],
        )
    ).fetchall()



    recent_attendance = cursor.execute(
        """
        SELECT *
        FROM attendance
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            session["user_id"],
        )
    ).fetchall()



    conn.close()



    return render_template(
        "student/dashboard.html",

        profile=profile,
        
        internship=internship,

        log_count=log_count,

        task_total=task_total,

        task_completed=task_completed,

        document_count=document_count,

        attendance_count=attendance_count,

        recent_logs=recent_logs,

        recent_tasks=recent_tasks,

        recent_documents=recent_documents,

        recent_attendance=recent_attendance
    )

@student.route("/student/clock-in", methods=["POST"])
@role_required("student")
def clock_in():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the student already has an open attendance session
    cursor.execute("""
        SELECT id
        FROM attendance
        WHERE student_id = ?
        AND status = 'Open'
    """, (session["user_id"],))

    existing_session = cursor.fetchone()

    if existing_session:
        conn.close()
        return redirect("/student/logbook")

    # Create a new attendance session

    clock_in = datetime.now()
    cursor.execute("""
        INSERT INTO attendance (
            student_id,
            clock_in,
            status
        )
        VALUES (
            ?,
            ?,
            ?
        )
    """, (session["user_id"], clock_in, "Open"))

    conn.commit()
    conn.close()

    return redirect("/student/logbook")

@student.route("/student/logbook")
@role_required("student")
def logbook():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Current attendance session
    cursor.execute("""
        SELECT
            id,
            clock_in,
            clock_out,
            hours_rendered,
            status
        FROM attendance
        WHERE student_id = ?
        AND status = 'Open'
    """, (session["user_id"],))

    attendance = cursor.fetchone()

    logs = []

    attendance = (
    attendance[0],
    format_time(attendance[1]),
    format_time(attendance[2]),
    attendance[3],
    attendance[4]
    ) if attendance else None

    # Load logs only if an open session exists
    if attendance:

        cursor.execute("""
            SELECT id, content, created_at
            FROM logs
            WHERE attendance_id = ?
            ORDER BY created_at DESC
        """, (attendance[0],))

        logs = cursor.fetchall()

        logs = [
            (
                log[0],
                log[1],
                format_time(log[2])
            )
            for log in logs
        ]

    # Attendance history
    cursor.execute("""
        SELECT id, clock_in, clock_out, hours_rendered, status
        FROM attendance
        WHERE student_id = ?
        ORDER BY clock_in DESC
    """, (session["user_id"],))

    history = cursor.fetchall()

    history = [
        (
            record[0],
            format_time(record[1]),
            format_time(record[2]),
            record[3],
            record[4]
        )
        for record in history
    ]

    conn.close()

    return render_template(
        "student/logbook.html",
        attendance=attendance,
        logs=logs,
        history=history,
        profile=get_student_profile(),
        active_page="logbook"
    )

@student.route("/student/clock-out", methods=["POST"])
@role_required("student")
def clock_out():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Find the student's current open attendance
    cursor.execute("""
        SELECT
            id,
            clock_in
        FROM attendance
        WHERE student_id = ?
        AND status = 'Open'
    """, (session["user_id"],))

    attendance = cursor.fetchone()

    if not attendance:
        conn.close()
        return redirect("/student/logbook")

    attendance_id = attendance[0]
    clock_in = parse_datetime(attendance[1])
    
    current_time = datetime.now()

    hours_rendered = max(
        0,
        round(
        (current_time - clock_in).total_seconds() / 3600,
        2
    )
    )

    cursor.execute("""
        UPDATE attendance
        SET clock_out = ?, hours_rendered = ?, status = 'Completed'
        WHERE id = ?
    """, (
        current_time,
        hours_rendered,
        attendance_id
    ))

    # Roll up completed hours to internships (keep student dashboard internship completed_hours in sync)
    try:
        cursor.execute("SELECT COALESCE(SUM(hours_rendered),0) FROM attendance WHERE student_id = ? AND status='Completed'", (session["user_id"],))
        total_hours = cursor.fetchone()[0] or 0
        cursor.execute("UPDATE internships SET completed_hours = ? WHERE student_id = ?", (total_hours, session["user_id"]))
    except Exception as e:
        print("hours rollup failed:", e)

    conn.commit()
    conn.close()

    return redirect("/student/logbook")

@student.route("/student/log/add", methods=["POST"])
@role_required("student")
def add_log():

    conn = get_db_connection()
    cursor = conn.cursor()

    content = request.form["content"].strip()

    if not content:
        conn.close()
        return redirect("/student/logbook")

    # Find the student's current open attendance session
    cursor.execute("""
        SELECT id
        FROM attendance
        WHERE student_id = ?
        AND status = 'Open'
    """, (session["user_id"],))

    attendance = cursor.fetchone()

    if not attendance:
        conn.close()
        return redirect("/student/logbook")

    attendance_id = attendance[0]

    # Insert log entry
    current_time = datetime.now()

    cursor.execute("""
        INSERT INTO logs (
            attendance_id,
            student_id,
            content,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        attendance_id,
        session["user_id"],
        content,
        current_time
    ))

    conn.commit()
    conn.close()

    return redirect("/student/logbook")

@student.route("/student/log/<int:log_id>/edit", methods=["GET", "POST"])
@role_required("student")
def edit_log(log_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            logs.id,
            logs.content,
            attendance.status
        FROM logs
        JOIN attendance
            ON logs.attendance_id = attendance.id
        WHERE logs.id = ?
        AND logs.student_id = ?
    """, (log_id, session["user_id"]))

    log = cursor.fetchone()

    if not log:
        conn.close()
        return "Log not found.", 404

    # Prevent editing after clock out
    if log[2] != "Open":
        conn.close()
        return redirect("/student/logbook")

    if request.method == "POST":

        content = request.form["content"].strip()

        if content:

            cursor.execute("""
                UPDATE logs
                SET content = ?
                WHERE id = ? AND student_id = ?
            """, (
                content,
                log_id,
                session["user_id"]
            ))

            conn.commit()

        conn.close()

        return redirect("/student/logbook")

    conn.close()

    return render_template(
        "student/edit_log.html",
        log=log,
        active_page="logbook"
    )

@student.route("/student/log/<int:log_id>/delete", methods=["POST"])
@role_required("student")
def delete_log(log_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify ownership and that the session is still open
    cursor.execute("""
        SELECT
            logs.id,
            attendance.status
        FROM logs
        JOIN attendance
            ON logs.attendance_id = attendance.id
        WHERE logs.id = ?
        AND logs.student_id = ?
    """, (log_id, session["user_id"]))

    log = cursor.fetchone()

    if not log:
        conn.close()
        return "Log not found.", 404

    if log[1] != "Open":
        conn.close()
        return redirect("/student/logbook")

    cursor.execute("""
        DELETE FROM logs
        WHERE id = ? AND student_id = ?
    """, (log_id, session["user_id"]))

    conn.commit()
    conn.close()

    return redirect("/student/logbook")

@student.route("/student/session/<int:attendance_id>")
@role_required("student")
def view_session(attendance_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Retrieve the attendance session
    cursor.execute("""
        SELECT
            id,
            clock_in,
            clock_out,
            hours_rendered,
            status
        FROM attendance
        WHERE id = ?
        AND student_id = ?
    """, (
        attendance_id,
        session["user_id"]
    ))

    attendance = cursor.fetchone()

    if not attendance:
        conn.close()
        return "Session not found.", 404

    # Retrieve all logs belonging to this attendance session
    cursor.execute("""
        SELECT id, content, created_at
        FROM logs
        WHERE attendance_id = ?
        ORDER BY created_at ASC
    """, (attendance_id,))

    logs = cursor.fetchall()

    attendance = list(attendance)

    attendance[1] = format_time(attendance[1])
    
    if attendance[2]:
        attendance[2] = format_time(attendance[2])
    
    logs = [
        (
            log[0],
            log[1],
                format_time(log[2])
        )
        for log in logs
    ]

    conn.close()

    return render_template(
        "student/session_details.html",
        attendance=attendance,
        logs=logs,
        active_page="logbook"
    )

@student.route('/student/tasks')
@role_required("student")
def tasks():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, task_title, assigned_at, deadline, status
        FROM tasks
        WHERE student_id = ?
        ORDER BY assigned_at DESC
    """, (session["user_id"],))

    tasks = cursor.fetchall()

    conn.close()

    return render_template(
        "student/tasks.html",
        tasks=tasks,
        active_page="tasks"
    )

@student.route("/student/task/<int:task_id>")
@role_required("student")
def task_details(task_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            task_title,
            task_description,
            assigned_at,
            deadline,
            status,
            requires_submission,
            allow_late_submission
        FROM tasks
        WHERE id = ?
        AND student_id = ?
    """, (task_id, session["user_id"]))

    task = cursor.fetchone()

    if not task:
        conn.close()
        return "Task not found.", 404

    cursor.execute("""
        SELECT id, filename, submitted_at
        FROM task_submissions
        WHERE task_id = ?
        ORDER BY submitted_at DESC
        """, (task_id,))

    uploads = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            filename,
            submitted_at,
            remarks
        FROM task_submissions
        WHERE task_id = ?
    """, (task_id,))

    submission = cursor.fetchone()

    conn.close()

    return render_template(
        "student/task_details.html",
        task=task,
        submission=submission,
        uploads=uploads,
        task_id=task_id,
        active_page="tasks"
    )

@student.route("/student/task/<int:task_id>/upload", methods=["POST"])
@role_required("student")
def task_upload(task_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # IDOR fix: verify task belongs to logged-in student via student_id
    cursor.execute("SELECT id FROM tasks WHERE id = ? AND student_id = ?", (task_id, session["user_id"]))
    if not cursor.fetchone():
        conn.close()
        return "Task not found or access denied", 404

    file = request.files.get("file")

    if file and file.filename:
        # Hardening: extension, MIME, size, secure path
        filename = secure_filename(file.filename)
        if not _allowed_file(filename, ALLOWED_DOC_EXTENSIONS):
            conn.close()
            return "File type not allowed", 400
        # MIME check
        mime, _ = mimetypes.guess_type(filename)
        if mime and not (mime.startswith("image/") or mime in ("application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/plain", "application/zip")):
            # allow but log; strict check for executables
            if "executable" in (mime or "") or filename.lower().endswith((".exe", ".sh", ".bat", ".php", ".py")):
                conn.close()
                return "Executable files not allowed", 400
        # size check via content_length or read
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > 5 * 1024 * 1024:
            conn.close()
            return "File too large (max 5MB)", 400
        # prevent overwrite collisions — prefix with user/task
        filename = f"{session['user_id']}_{task_id}_{filename}"
        filepath = os.path.join(
            current_app.config["UPLOAD_FOLDER"],
            filename
        )
        if not _is_safe_path(current_app.config["UPLOAD_FOLDER"], filepath):
            conn.close()
            return "Invalid path", 400

        file.save(filepath)

        # Remove previous submission (one upload only)
        cursor.execute("""
            DELETE FROM task_submissions
            WHERE task_id = ?
        """, (task_id,))

        cursor.execute("""
            INSERT INTO task_submissions
            (task_id, filename, filepath)
            VALUES (?, ?, ?)
        """, (
            task_id,
            filename,
            filepath
        ))

        conn.commit()

    conn.close()

    return redirect(f"/student/task/{task_id}")

@student.route("/student/task/submission/<int:submission_id>")
@role_required("student")
def view_task_submission(submission_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ts.filename,
            ts.filepath
        FROM task_submissions ts
        JOIN tasks t
            ON ts.task_id = t.id
        WHERE ts.id = ?
        AND t.student_id = ?
    """, (submission_id, session["user_id"]))

    submission = cursor.fetchone()

    conn.close()

    if not submission:
        return "Submission not found.", 404

    filepath = submission[1]
    filename = submission[0]
    upload_base = current_app.config.get("UPLOAD_FOLDER", "")
    if upload_base and not _is_safe_path(upload_base, filepath):
        return "Invalid file path.", 403
    if not os.path.exists(filepath):
        return "File not found.", 404
    return send_file(
        filepath,
        as_attachment=False,
        download_name=filename
    )

@student.route("/student/task/submission/<int:submission_id>/delete", methods=["POST"])
@role_required("student")
def delete_task_submission(submission_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ts.task_id,
            ts.filepath
        FROM task_submissions ts
        JOIN tasks t
            ON ts.task_id = t.id
        WHERE ts.id = ?
        AND t.student_id = ?
    """, (submission_id, session["user_id"]))

    submission = cursor.fetchone()

    if not submission:
        conn.close()
        return "Submission not found.", 404

    task_id = submission[0]
    filepath = submission[1]

    upload_base = current_app.config.get("UPLOAD_FOLDER", "")
    if upload_base and not _is_safe_path(upload_base, filepath):
        conn.close()
        return "Invalid file path.", 403
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except:
            pass

    cursor.execute("""
        DELETE FROM task_submissions
        WHERE id = ?
    """, (submission_id,))

    conn.commit()
    conn.close()

    return redirect(f"/student/task/{task_id}")

@student.route("/student/task/<int:task_id>/submit", methods=["POST"])
@role_required("student")
def submit_task(task_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify the task belongs to the logged-in student and fetch lifecycle fields
    cursor.execute("""
        SELECT id, status, requires_submission, deadline, allow_late_submission, supervisor_id, task_title
        FROM tasks
        WHERE id = ?
        AND student_id = ?
    """, (task_id, session["user_id"]))

    task = cursor.fetchone()

    if not task:
        conn.close()
        return "Task not found.", 404

    # Normalize row access (HybridRow vs sqlite Row)
    try:
        status = task["status"]
        requires_submission = task["requires_submission"]
        deadline = task["deadline"]
        allow_late = task["allow_late_submission"]
        supervisor_id = task["supervisor_id"]
        task_title = task["task_title"]
    except:
        status = task[1]
        requires_submission = task[2]
        deadline = task[3]
        allow_late = task[4]
        supervisor_id = task[5]
        task_title = task[6]

    if status not in ("Pending", "Reopened"):
        conn.close()
        flash("Only Pending/Reopened tasks can be submitted.", "warning")
        return redirect(f"/student/task/{task_id}")

    if requires_submission:
        cursor.execute("SELECT COUNT(*) FROM task_submissions WHERE task_id = ?", (task_id,))
        cnt = cursor.fetchone()[0]
        if cnt == 0:
            conn.close()
            flash("File submission required before submitting.", "danger")
            return redirect(f"/student/task/{task_id}")

    if deadline and not allow_late:
        try:
            dt = parse_datetime(deadline)
            if dt and datetime.now() > dt:
                conn.close()
                flash("Deadline passed and late submission not allowed.", "danger")
                return redirect(f"/student/task/{task_id}")
        except:
            pass

    # Mark task as submitted — include student_id guard (IDOR)
    cursor.execute("""
        UPDATE tasks
        SET status = 'Submitted'
        WHERE id = ? AND student_id = ?
    """, (task_id, session["user_id"]))

    conn.commit()
    # Notify supervisor (existing service)
    try:
        if supervisor_id:
            create_notification(supervisor_id, "Task Submitted", f"Student submitted task: {task_title}", "task", link_url=f"/supervisor/task/{task_id}")
    except Exception as e:
        print("submit_task notification failed:", e)
    conn.close()

    flash("Task submitted successfully.", "success")
    return redirect(f"/student/task/{task_id}")

#documents

@student.route('/student/documents', methods=['GET', 'POST'])
@role_required("student")
def documents():
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        file = request.files.get('file')
        if file and file.filename:
            filename = secure_filename(file.filename)
            if not _allowed_file(filename, ALLOWED_DOC_EXTENSIONS):
                conn.close()
                return "File type not allowed", 400
            if filename.lower().endswith((".exe",".sh",".bat",".php",".py")):
                conn.close()
                return "Executable files not allowed", 400
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            if size > 5 * 1024 * 1024:
                conn.close()
                return "File too large (max 5MB)", 400
            filename = f"{session['user_id']}_{filename}"
            filepath = os.path.join(
                current_app.config['UPLOAD_FOLDER'],
                filename
                )
            if not _is_safe_path(current_app.config["UPLOAD_FOLDER"], filepath):
                conn.close()
                return "Invalid path", 400
            file.save(filepath)

            cursor.execute(
                "INSERT INTO documents (student_id, filename, filepath) VALUES (?, ?, ?)",
                (session['user_id'], filename, filepath)
            )
            conn.commit()

    cursor.execute(
        """
        SELECT id, filename, uploaded_at
        FROM documents
        WHERE student_id = ?
        ORDER BY uploaded_at DESC
        """,
        (session['user_id'],)
    )
    docs = cursor.fetchall()
    conn.close()

    return render_template('student/documents.html', docs=docs, active_page="documents")

@student.route("/student/document/<int:document_id>")
@role_required("student")
def view_document(document_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT filename, filepath
        FROM documents
        WHERE id = ?
        AND student_id = ?
    """, (document_id, session["user_id"]))

    document = cursor.fetchone()

    conn.close()

    if not document:
        return "Document not found.", 404

    filepath = document[1]
    filename = document[0]
    upload_base = current_app.config.get("UPLOAD_FOLDER", "")
    if upload_base and not _is_safe_path(upload_base, filepath):
        return "Invalid file path.", 403
    if not os.path.exists(filepath):
        return "File not found.", 404
    return send_file(
        filepath,
        as_attachment=False,
        download_name=filename
    )

@student.route(
    "/student/profile/setup",
    methods=["GET", "POST"]
)
@role_required("student")
def profile_setup():

    conn = get_db_connection()
    cursor = conn.cursor()


    if request.method == "POST":

        # Server-side validation — never trust browser (profile_setup was missing this)
        first_name = (request.form.get("first_name") or "").strip()
        middle_name = (request.form.get("middle_name") or "").strip()
        last_name = (request.form.get("last_name") or "").strip()
        age_raw = (request.form.get("age") or "").strip()
        age = age_raw
        student_id = (request.form.get("student_id") or "").strip()
        phone_number = (request.form.get("phone_number") or "").strip()
        home_address = (request.form.get("home_address") or "").strip()
        grade_year = (request.form.get("grade_year") or "").strip()
        major_program = (request.form.get("major_program") or "").strip()
        errors = {}
        if not first_name or not first_name.replace(" ", "").isalpha():
            errors["first_name"] = "First name required, letters only."
        if not last_name or not last_name.replace(" ", "").isalpha():
            errors["last_name"] = "Last name required, letters only."
        if middle_name and not middle_name.replace(" ", "").isalpha():
            errors["middle_name"] = "Middle name letters only."
        if not student_id:
            errors["student_id"] = "Student ID required."
        if not grade_year:
            errors["grade_year"] = "Grade/year required."
        if not major_program:
            errors["major_program"] = "Major/program required."
        if age_raw:
            try:
                age_int = int(age_raw)
                if age_int < 15 or age_int > 100:
                    errors["age"] = "Age 15-100."
                else:
                    age = age_int
            except:
                errors["age"] = "Age must be number."
        else:
            age = None
        if phone_number and (not phone_number.isdigit() or len(phone_number) < 7 or len(phone_number) > 15):
            errors["phone_number"] = "Phone 7-15 digits."
        if errors:
            for f, msg in errors.items():
                flash(f"{f}: {msg}", "danger")
            conn.close()
            return redirect("/student/profile/setup")



        # ==========================
        # PROFILE PICTURE
        # ==========================

        profile_picture = None


        cropped_image = request.form.get(
            "cropped_image"
        )


        if cropped_image:
            import base64

            try:
                if "," in cropped_image:
                    image_data = cropped_image.split(",")[1]
                else:
                    image_data = cropped_image
                # size check — base64 ~ 4/3 of binary, limit 2MB binary ~ 2.7MB b64
                if len(image_data) > 4 * 1024 * 1024:
                    conn.close()
                    return "Image too large", 400
                decoded = base64.b64decode(image_data, validate=True)
                if len(decoded) > MAX_IMAGE_SIZE:
                    conn.close()
                    return "Image too large (max 2MB)", 400
                # basic image header check (jpeg/png/gif)
                if not (decoded.startswith(b"\xff\xd8") or decoded.startswith(b"\x89PNG") or decoded.startswith(b"GIF")):
                    # allow but log; still write for now
                    pass
            except Exception:
                conn.close()
                return "Invalid image data", 400

            filename = (
                str(session["user_id"])
                +
                "_profile.jpg"
            )

            filepath = os.path.join(
                current_app.config["PROFILE_UPLOAD_FOLDER"],
                filename
            )
            if not _is_safe_path(current_app.config["PROFILE_UPLOAD_FOLDER"], filepath):
                conn.close()
                return "Invalid path", 400

            with open(filepath, "wb") as file:
                file.write(decoded)

            profile_picture = filename



        # ==========================
        # UPDATE PROFILE
        # ==========================


        cursor.execute(
            """
            UPDATE student_profiles

            SET

            first_name = ?,
            middle_name = ?,
            last_name = ?,
            age = ?,
            student_id = ?,
            profile_picture = ?,
            phone_number = ?,
            home_address = ?,
            grade_year = ?,
            major_program = ?,
            profile_completed = 1


            WHERE user_id = ?

            """,
            (

                first_name,
                middle_name,
                last_name,

                age,

                student_id,

                profile_picture,

                phone_number,

                home_address,

                grade_year,

                major_program,

                session["user_id"]

            )
        )


        conn.commit()

        conn.close()


        flash(
            "Profile completed successfully!",
            "success"
        )


        return redirect(
            "/student/dashboard"
        )



    conn.close()


    return render_template(
        "student/profile_setup.html"
    )


@student.route("/student/profile")
@role_required("student")
def student_profile():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
        first_name,
        middle_name,
        last_name,
        age,
        student_id,
        profile_picture,
        phone_number,
        home_address,
        grade_year,
        major_program,
        emergency_name,
        emergency_relationship,
        emergency_phone,
        emergency_email,
        users.email

    FROM student_profiles

    JOIN users
    ON student_profiles.user_id = users.id

    WHERE student_profiles.user_id = ?

    """,
    (
        session["user_id"],
    ))

    profile = cursor.fetchone()
    
        # ==========================
    # PROFILE COMPLETION
    # ==========================

    fields = [

        profile[0],
        profile[1],
        profile[2],
        profile[3],
        profile[4],
        profile[5],
        profile[6],
        profile[7],
        profile[8],
        profile[9],
        profile[10],
        profile[11],
        profile[12]

    ]


    completed = sum(
        1 for field in fields
        if field
    )


    profile_percentage = int(
        (completed / len(fields)) * 100
    )

    conn.close()

    return render_template(
        "student/profile.html",
        profile=profile,
        profile_percentage=profile_percentage,
        active_page="profile"
    )
    
@student.route(
    "/student/profile/edit",
    methods=["GET", "POST"]
)
@role_required("student")
def edit_profile():


    if request.method == "POST":


        profile_data = get_student_profile_data(
            request.form
        )


        # ==========================
        # PROFILE VALIDATION
        # ==========================


        age = profile_data.get("age")


        if age:

            try:

                age = int(age)

                if age < 15 or age > 100:

                    flash(
                        "Invalid age entered.",
                        "error"
                    )

                    return redirect(
                        "/student/profile/edit"
                    )


                profile_data["age"] = age


            except ValueError:

                flash(
                    "Age must be a number.",
                    "error"
                )

                return redirect(
                    "/student/profile/edit"
                )



        # Student cannot change Student ID

        conn = get_db_connection()

        cursor = conn.cursor()


        cursor.execute(
            """
            SELECT student_id
            FROM student_profiles
            WHERE user_id = ?
            """,
            (
                session["user_id"],
            )
        )


        current_student_id = cursor.fetchone()[0]


        conn.close()



        profile_data["student_id"] = current_student_id


        profile_data["grade_year"] = format_title_case(
            profile_data["grade_year"]
        )


        profile_data["major_program"] = format_title_case(
            profile_data["major_program"]
        )
        
        errors = {}


        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        middle_name = request.form.get("middle_name")
        age = request.form.get("age")
        phone = request.form.get("phone_number")
        student_id = request.form.get("student_id")


        # REQUIRED CHECK

        if not first_name:
            errors["first_name"] = "First name is required."

        elif not first_name.replace(" ", "").isalpha():
            errors["first_name"] = "First name must contain letters only."


        if not last_name:
            errors["last_name"] = "Last name is required."

        elif not last_name.replace(" ", "").isalpha():
            errors["last_name"] = "Last name must contain letters only."
            
        if middle_name:

            if not middle_name.replace(" ", "").isalpha():

                errors["middle_name"] = "Middle name must contain letters only."


        if not student_id:
            errors["student_id"] = "Student ID is required."



        # AGE CHECK

        if age:

            try:

                age_number = int(age)

                if age_number < 15 or age_number > 100:
                    errors["age"] = "Age must be between 15 and 100."

            except:

                errors["age"] = "Age must be a valid number."



        # PHONE CHECK

        if phone:

            if not phone.isdigit():

                errors["phone_number"] = "Phone number must contain numbers only."



        # STOP SAVE IF ERRORS

        if errors:

            flash(
                "Please fix the highlighted fields.",
                "error"
            )


            student = {
                "first_name": request.form.get("first_name"),
                "middle_name": request.form.get("middle_name"),
                "last_name": request.form.get("last_name"),
                "age": request.form.get("age"),
                "student_id": request.form.get("student_id"),
                "phone_number": request.form.get("phone_number"),
                "home_address": request.form.get("home_address"),
                "grade_year": request.form.get("grade_year"),
                "major_program": request.form.get("major_program"),
                "emergency_name": request.form.get("emergency_name"),
                "emergency_relationship": request.form.get("emergency_relationship"),
                "emergency_phone": request.form.get("emergency_phone"),
                "emergency_email": request.form.get("emergency_email"),
                "email": session.get("email", "")
            }


            return render_template(
                "student/profile_edit.html",
                student=student,
                errors=errors
            )

        update_student_profile(
            session["user_id"],
            profile_data
        )


        flash(
            "Profile updated successfully!",
            "success"
        )


        return redirect(
            "/student/profile"
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            first_name,
            middle_name,
            last_name,
            age,
            student_id,
            profile_picture,
            phone_number,
            home_address,
            grade_year,
            major_program,
            emergency_name,
            emergency_relationship,
            emergency_phone,
            emergency_email

        FROM student_profiles

        WHERE user_id = ?

    """,
    (
        session["user_id"],
    ))


    profile = cursor.fetchone()

    if not profile:
        conn.close()
        flash("Please complete your profile setup first.", "warning")
        return redirect("/student/profile/setup")

    cursor.execute("""
        SELECT email
        FROM users
        WHERE id = ?
    """, (session["user_id"],))

    user_email = cursor.fetchone()[0]


    student = {
        "id": session["user_id"],
        "first_name": profile[0],
        "middle_name": profile[1],
        "last_name": profile[2],
        "age": profile[3],
        "student_id": profile[4],
        "profile_picture": profile[5],
        "phone_number": profile[6],
        "home_address": profile[7],
        "grade_year": profile[8],
        "major_program": profile[9],
        "emergency_name": profile[10],
        "emergency_relationship": profile[11],
        "emergency_phone": profile[12],
        "emergency_email": profile[13],
        "email": user_email
    }


    return render_template(
        "student/profile_edit.html",
        student=student
    )
    
    
    
@student.route(
    "/student/profile/photo",
    methods=["POST"]
)
@role_required("student")
def update_profile_photo():

    file = request.files.get(
        "profile_picture"
    )


    if not file or not file.filename:
        return "No image received", 400

    # Validate image extension/MIME
    orig_name = secure_filename(file.filename)
    if not _allowed_file(orig_name, ALLOWED_IMAGE_EXTENSIONS):
        return "Image type not allowed (png/jpg/jpeg/gif only)", 400
    mime, _ = mimetypes.guess_type(orig_name)
    if mime and not mime.startswith("image/"):
        return "Invalid image", 400
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_IMAGE_SIZE:
        return "Image too large (max 2MB)", 400

    filename = (
        str(session["user_id"])
        +
        "_profile.jpg"
    )


    filepath = os.path.join(
        current_app.config["PROFILE_UPLOAD_FOLDER"],
        filename
    )
    if not _is_safe_path(current_app.config["PROFILE_UPLOAD_FOLDER"], filepath):
        return "Invalid path", 400


    file.save(filepath)


    conn = get_db_connection()
    cursor = conn.cursor()


    cursor.execute(
        """
        UPDATE student_profiles
        SET profile_picture = ?
        WHERE user_id = ?
        """,
        (
            filename,
            session["user_id"]
        )
    )


    conn.commit()
    conn.close()


    return "OK"