from flask import Blueprint, render_template, request, redirect, session
from routes.security import role_required
import os
from database.db import get_db_connection
from datetime import datetime
from ml.predictor import analyze_feedback

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


def format_datetime(timestamp):
    dt = parse_datetime(timestamp)

    if not dt:
        return None

    return dt.strftime("%b %d, %Y • %I:%M %p").lstrip("0")

supervisor = Blueprint("supervisor", __name__)

# Dashboard
@supervisor.route("/supervisor/dashboard")
@role_required("supervisor")
def supervisor_dashboard():

    conn = get_db_connection()
    cursor = conn.cursor()

    supervisor_id = session["user_id"]


    # Count assigned interns
    cursor.execute("""
        SELECT COUNT(*)
        FROM student_assignments
        WHERE supervisor_id = ?
    """, (supervisor_id,))

    total_interns = cursor.fetchone()[0]


    # Count active attendance sessions
    cursor.execute("""
        SELECT COUNT(*)
        FROM attendance a
        JOIN student_assignments sa
        ON a.student_id = sa.student_id
        WHERE sa.supervisor_id = ?
        AND a.status = 'Open'
    """, (supervisor_id,))

    active_sessions = cursor.fetchone()[0]

    # Display active interns
    cursor.execute("""
        SELECT
            u.username,
            a.clock_in
        FROM attendance a

        JOIN users u
        ON a.student_id = u.id

        JOIN student_assignments sa
        ON a.student_id = sa.student_id

        WHERE sa.supervisor_id = ?
        AND a.status = 'Open'

        ORDER BY a.clock_in ASC
    """, (supervisor_id,))

    active_interns = cursor.fetchall()
    
    active_interns = [
    (
        intern[0],
        format_time(intern[1])
    )
    for intern in active_interns
    ]

    # Recent logs from assigned interns
    cursor.execute("""
        SELECT
        u.username,
            l.content,
            l.created_at,
            l.student_id
        FROM logs l

        JOIN users u
        ON l.student_id = u.id

        JOIN student_assignments sa
        ON l.student_id = sa.student_id

        WHERE sa.supervisor_id = ?

        ORDER BY l.created_at DESC

        LIMIT 5
    """, (supervisor_id,))

    acts = cursor.fetchall()

    acts = [
    (
        act[0],
        act[1],
        format_datetime(act[2]),
        act[3]
    )
    for act in acts 
    ]

    # Recent tasks
    cursor.execute("""
        SELECT
            t.task_title,
            u.username,
            t.status,
            t.deadline

        FROM tasks t

        JOIN users u
        ON t.student_id = u.id

        JOIN student_assignments sa
        ON t.student_id = sa.student_id

        WHERE sa.supervisor_id = ?

        ORDER BY t.id DESC

        LIMIT 5
    """, (supervisor_id,))

    recent_tasks = cursor.fetchall()
    
    recent_tasks = [
    (
        task[0],
        task[1],
        task[2],
        format_datetime(task[3])
    )
    for task in recent_tasks
    ]

    conn.close()


    return render_template(
        "supervisor/dashboard.html",

        active_page="dashboard",

        total_interns=total_interns,
        active_sessions=active_sessions,
        active_interns=active_interns,
        acts=acts,
        recent_tasks=recent_tasks
    )

# view interns
@supervisor.route("/supervisor/interns")
@role_required("supervisor")
def view_interns():
    conn = get_db_connection()

    students = conn.execute("""
        SELECT users.id, users.username
        FROM users
        JOIN student_assignments
        ON users.id = student_assignments.student_id
        WHERE student_assignments.supervisor_id = ?
    """, (session["user_id"],)).fetchall()

    conn.close()
    return render_template("supervisor/interns.html", students=students, active_page="interns")


#  View student profile 
@supervisor.route("/supervisor/student/<int:student_id>")
@role_required("supervisor")
def view_student(student_id):
    conn = get_db_connection()

    # Student info
    student = conn.execute(
        "SELECT username FROM users WHERE id = ?",
        (student_id,)
    ).fetchone()

    if not student:
        conn.close()
        return "Student not found"

    # Sessions / Attendance
    sessions = conn.execute("""
        SELECT id, clock_in, clock_out, hours_rendered, status
        FROM attendance
        WHERE student_id = ?
        ORDER BY clock_in DESC
        LIMIT 5
    """, (student_id,)).fetchall()

    sessions = [(
        session[0],
        format_datetime(session[1]),
        format_datetime(session[2]),
        session[3],
        session[4]
    )
    for session in sessions
    ]

    # Tasks
    tasks = conn.execute("""
        SELECT id, task_title, assigned_at, deadline, status
        FROM tasks
        WHERE student_id = ?
        ORDER BY assigned_at DESC
    """, (student_id,)).fetchall()

    # Documents
    docs = conn.execute("""
        SELECT filename, uploaded_at
        FROM documents
        WHERE student_id = ?
    """, (student_id,)).fetchall()

    # Feedback history
    feedback = conn.execute("""
        SELECT comment, created_at, performance_label
        FROM feedback
        WHERE student_id = ?
        ORDER BY created_at DESC
        """, (student_id,)).fetchall()

    conn.close()

    return render_template(
        "supervisor/student_profile.html",
        student=student,
        sessions=sessions,
        tasks=tasks,
        docs=docs,
        feedback=feedback,
        student_id=student_id,
        active_page="interns"
    )


# ---------------- ADD FEEDBACK ----------------
@supervisor.route("/supervisor/student/<int:student_id>/feedback", methods=["POST"])
@role_required("supervisor")
def add_feedback(student_id):

    comment = request.form["comment"]
    label = request.form["label"]

    ml_prediction = analyze_feedback(comment)

    conn = get_db_connection()

    conn.execute(
        """
        INSERT INTO feedback 
        (student_id, supervisor_id, comment, performance_label)
        VALUES (?, ?, ?, ?)
        """,
        (
            student_id,
            session["user_id"],
            comment,
            label
        )
    )

    conn.commit()
    conn.close()

    return redirect(f"/supervisor/student/{student_id}")

# ---------------- ASSIGN TASK 
@supervisor.route("/supervisor/student/<int:student_id>/assign-task", methods=["GET", "POST"])
@role_required("supervisor")
def assign_task(student_id):

    conn = get_db_connection()


    # Retrieve student information
    student = conn.execute("""
        SELECT username
        FROM users
        WHERE id = ?
    """, (student_id,)).fetchone()


    if not student:

        conn.close()

        return "Student not found"


    if request.method == "POST":

        task_title = request.form["task_title"]

        task_description = request.form["task_description"]

        deadline = request.form.get("deadline") or None

        requires_submission = (
            1 if request.form.get("requires_submission") else 0
        )

        allow_late_submission = (
            1 if request.form.get("allow_late_submission") else 0
        )


        conn.execute("""
            INSERT INTO tasks (
                student_id,
                supervisor_id,
                task_title,
                task_description,
                deadline,
                requires_submission,
                allow_late_submission
            )

            VALUES (?, ?, ?, ?, ?, ?, ?)

        """, (

            student_id,

            session["user_id"],

            task_title,

            task_description,

            deadline,

            requires_submission,

            allow_late_submission

        ))


        conn.commit()

        conn.close()


        return redirect(
            f"/supervisor/student/{student_id}"
        )


    conn.close()


    return render_template(

        "supervisor/assign_task.html",

        student=student,

        student_id=student_id,

        active_page="assign_task"

    )

# View, Edit, Delete, Reopen, and Toggle Tasks #

# View #
@supervisor.route("/supervisor/task/<int:task_id>")
@role_required("supervisor")
def view_task(task_id):

    conn = get_db_connection()
    task = conn.execute("""
    SELECT
        tasks.id,
        tasks.student_id,
        tasks.task_title,
        tasks.task_description,
        tasks.assigned_at,
        tasks.deadline,
        tasks.requires_submission,
        tasks.allow_late_submission,
        tasks.status,
        users.username
    FROM tasks
    JOIN users
        ON tasks.student_id = users.id
    WHERE tasks.id = ?
    AND tasks.supervisor_id = ?
    """, (
    task_id, session["user_id"])).fetchone()

    if not task:

        conn.close()

        return "Task not found"

    submissions = conn.execute("""
        SELECT
            id,
            filename,
            filepath,
            submitted_at,
            remarks
        FROM task_submissions
        WHERE task_id = ?
        ORDER BY submitted_at DESC
    """, (task_id,)).fetchall()

    conn.close()

    return render_template(
        "supervisor/view_task.html",
        task=task,
        submissions=submissions,
        active_page="interns"
    )

# Edit #
@supervisor.route("/supervisor/task/<int:task_id>/edit", methods=["GET", "POST"])
@role_required("supervisor")
def edit_task(task_id):

    conn = get_db_connection()

    # Get current task
    task = conn.execute("""
        SELECT
            id,
            student_id,
            task_title,
            task_description,
            deadline,
            requires_submission,
            allow_late_submission,
            status
        FROM tasks
        WHERE id = ?
        AND supervisor_id = ?
    """, (task_id, session["user_id"])).fetchone()

    # Not a task, or wrong supervisor
    if not task:

        conn.close()

        return "Task not found or access denied", 404

    # Save changes
    if request.method == "POST":

        task_title = request.form["task_title"]

        task_description = request.form["task_description"]

        deadline = request.form.get("deadline") or None

        requires_submission = (
            1 if request.form.get("requires_submission") else 0
        )

        allow_late_submission = (
            1 if request.form.get("allow_late_submission") else 0
        )

        conn.execute("""
            UPDATE tasks

            SET
                task_title = ?,
                task_description = ?,
                deadline = ?,
                requires_submission = ?,
                allow_late_submission = ?

            WHERE id = ?

            AND supervisor_id = ?
        """, (
            task_title,
            task_description,
            deadline,
            requires_submission,
            allow_late_submission,
            task_id,
            session["user_id"]
        ))

        conn.commit()

        student_id = task["student_id"]

        conn.close()

        return redirect(
            f"/supervisor/task/{task_id}"
        )

    student_id = task["student_id"]
    conn.close()

    return render_template(
        "supervisor/edit_task.html",
        task=task,
        task_id=task_id,
        student_id=student_id,
        active_page="edit_task"
    )

# Delete #
@supervisor.route("/supervisor/task/<int:task_id>/delete", methods=["POST"])
@role_required("supervisor")
def delete_task(task_id):

    conn = get_db_connection()

    task = conn.execute("""
        SELECT student_id
        FROM tasks
        WHERE id = ?
        AND supervisor_id = ?
    """, ( task_id, session["user_id"])).fetchone()

    if not task:
        conn.close()

        return "Task not found or access denied", 404

    student_id = task[0]

    # Delete related submissions first
    conn.execute("""
        DELETE FROM task_submissions
        WHERE task_id = ?

    """, (task_id,))

    # Delete the task
    conn.execute("""
        DELETE FROM tasks
        WHERE id = ?
        AND supervisor_id = ?
    """, (
        task_id,
        session["user_id"]
    ))

    conn.commit()
    conn.close()

    return redirect(
        f"/supervisor/student/{student_id}"
    )