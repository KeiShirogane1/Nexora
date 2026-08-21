from flask import Blueprint, current_app, render_template, request, redirect, session, send_file
from routes.security import role_required
from database.db import get_db_connection
import os
from werkzeug.utils import secure_filename
from datetime import datetime


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

@student.route("/student/dashboard")
@role_required("student")
def student_dashboard():
    return render_template("student/dashboard.html", active_page="dashboard")

from flask import request, redirect, session

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
                WHERE id = ?
            """, (
                content,
                log_id
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
        WHERE id = ?
    """, (log_id,))

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

    file = request.files.get("file")

    if file and file.filename:

        filename = secure_filename(file.filename)

        filepath = os.path.join(
            current_app.config["UPLOAD_FOLDER"],
            filename
        )

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

    return send_file(
        submission[1],
        as_attachment=False
    )

@student.route("/student/task/submission/<int:submission_id>/delete")
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

    if os.path.exists(filepath):
        os.remove(filepath)

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

    # Verify the task belongs to the logged-in student
    cursor.execute("""
        SELECT id
        FROM tasks
        WHERE id = ?
        AND student_id = ?
    """, (task_id, session["user_id"]))

    task = cursor.fetchone()

    if not task:
        conn.close()
        return "Task not found.", 404

    # Mark task as submitted
    cursor.execute("""
        UPDATE tasks
        SET status = 'Submitted'
        WHERE id = ?
    """, (task_id,))

    conn.commit()
    conn.close()

    return redirect(f"/student/task/{task_id}")

#documents

@student.route('/student/documents', methods=['GET', 'POST'])
@role_required("student")
def documents():
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        file = request.files['file']

        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(
                current_app.config['UPLOAD_FOLDER'],
                filename
                )
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

    return send_file(
        document[1],
        as_attachment=False
    )

