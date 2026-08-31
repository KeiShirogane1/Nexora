from flask import Blueprint, render_template, request, redirect, session, send_file, current_app, flash
from app.Http.Middleware.security import role_required
import os
import mimetypes
from app.Models.db import get_db_connection
from datetime import datetime
from app.ML.predictor import analyze_feedback, analyze_feedback_detailed
from app.Services.notification_service import create_notification

def _is_safe_path(base, target):
    try:
        base_abs = os.path.abspath(base)
        target_abs = os.path.abspath(target)
        return os.path.commonpath([base_abs]) == os.path.commonpath([base_abs, target_abs])
    except:
        return False

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

@supervisor.before_request
def _check_supervisor_active():
    # Only for supervisor routes with a logged in supervisor
    if "user_id" in session and session.get("role") == "supervisor":
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT status FROM users WHERE id = ?", (session.get("user_id"),)).fetchone()
            if row is not None:
                status = None
                try:
                    status = row["status"]  # HybridRow / sqlite Row
                except:
                    try:
                        status = row[0]
                    except:
                        status = None
                if status == "inactive":
                    return "Account deactivated — contact administrator.", 403
        finally:
            conn.close()

def _is_assigned(supervisor_id, student_id):
    """Check student_assignments ownership — supervisor may only access assigned students."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM student_assignments WHERE supervisor_id = ? AND student_id = ?",
            (supervisor_id, student_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()

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
        SELECT users.id, users.username, sp.major_program, sp.grade_year, i.company_name, i.position, i.status as internship_status
        FROM users
        JOIN student_assignments sa ON users.id = sa.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = users.id
        LEFT JOIN internships i ON i.student_id = users.id AND i.status = 'Active'
        WHERE sa.supervisor_id = ?
        GROUP BY users.id
        ORDER BY users.username
    """, (session["user_id"],)).fetchall()

    conn.close()
    return render_template("supervisor/interns.html", students=students, active_page="interns")


#  View student profile 
@supervisor.route("/supervisor/student/<int:student_id>")
@role_required("supervisor")
def view_student(student_id):
    # Ownership: supervisor may only view assigned students
    if not _is_assigned(session.get("user_id"), student_id):
        return "Forbidden — student not assigned to you", 403
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

    # Documents (include id for secure supervisor download link)
    docs = conn.execute("""
        SELECT id, filename, uploaded_at
        FROM documents
        WHERE student_id = ?
        ORDER BY uploaded_at DESC
    """, (student_id,)).fetchall()

    # Feedback history — prefer stored ML, fallback to predictor for legacy NULLs
    try:
        raw_feedback = conn.execute("""
            SELECT comment, created_at, performance_label,
                   ml_prediction, ml_sentiment, ml_competency,
                   ml_recommendation, ml_svm_prediction, ml_confidence
            FROM feedback
            WHERE student_id = ?
            ORDER BY created_at DESC
            """, (student_id,)).fetchall()
    except Exception:
        # legacy DB without ML cols
        raw_feedback = conn.execute("""
            SELECT comment, created_at, performance_label
            FROM feedback
            WHERE student_id = ?
            ORDER BY created_at DESC
            """, (student_id,)).fetchall()

    # Enrich each row: ensure ML fields present via predictor fallback
    feedback = []
    for fb in raw_feedback:
        try:
            # Handle variable column count via keys or index
            comment = fb["comment"] if "comment" in fb.keys() else fb[0]
            created = fb["created_at"] if "created_at" in fb.keys() else fb[1]
            perf_label = fb["performance_label"] if "performance_label" in fb.keys() else fb[2]
            # try stored ML
            ml_pred = None
            ml_sent = None
            ml_comp = None
            ml_rec = None
            ml_svm = None
            ml_conf = None
            try:
                ml_pred = fb["ml_prediction"] if "ml_prediction" in fb.keys() else (fb[3] if len(fb) > 3 else None)
                ml_sent = fb["ml_sentiment"] if "ml_sentiment" in fb.keys() else (fb[4] if len(fb) > 4 else None)
                ml_comp = fb["ml_competency"] if "ml_competency" in fb.keys() else (fb[5] if len(fb) > 5 else None)
                ml_rec = fb["ml_recommendation"] if "ml_recommendation" in fb.keys() else (fb[6] if len(fb) > 6 else None)
                ml_svm = fb["ml_svm_prediction"] if "ml_svm_prediction" in fb.keys() else (fb[7] if len(fb) > 7 else None)
                ml_conf = fb["ml_confidence"] if "ml_confidence" in fb.keys() else (fb[8] if len(fb) > 8 else None)
            except Exception:
                pass
            # Fallback for legacy NULLs using predictor
            if not ml_pred or not ml_sent:
                try:
                    from app.ML.predictor import analyze_feedback_detailed as _afd
                    d = _afd(comment)
                    if not ml_pred:
                        ml_pred = d.get("performance_label")
                    if not ml_sent:
                        ml_sent = d.get("sentiment")
                    if not ml_comp:
                        ml_comp = d.get("competency")
                    if not ml_rec:
                        ml_rec = d.get("recommendation")
                    if not ml_svm:
                        ml_svm = d.get("svm_prediction")
                    if ml_conf is None:
                        ml_conf = d.get("confidence")
                except Exception:
                    pass
            # Normalise confidence
            try:
                ml_conf = float(ml_conf) if ml_conf is not None else 0.0
            except Exception:
                ml_conf = 0.0
            feedback.append((comment, created, perf_label, ml_pred, ml_sent, ml_comp, ml_rec, ml_svm, ml_conf))
        except Exception:
            # last resort: append as-is
            feedback.append(tuple(fb))

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
    if not _is_assigned(session.get("user_id"), student_id):
        return "Forbidden — student not assigned to you", 403

    comment = (request.form.get("comment") or "").strip()
    label = (request.form.get("label") or "").strip()
    allowed_labels = {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}
    if not comment:
        flash("Feedback comment is required.", "danger")
        return redirect(f"/supervisor/student/{student_id}")
    if len(comment) < 3 or len(comment) > 2000:
        flash("Feedback must be 3-2000 characters.", "danger")
        return redirect(f"/supervisor/student/{student_id}")
    if label not in allowed_labels:
        flash("Invalid performance rating.", "danger")
        return redirect(f"/supervisor/student/{student_id}")

    # Thesis ML pipeline: TF-IDF -> NB+SVM -> sentiment/competency/recommendation
    try:
        ml_result = analyze_feedback_detailed(comment)
    except Exception:
        # fallback to string api never crash on invalid text
        ml_result = {
            "performance_label": analyze_feedback(comment),
            "svm_prediction": analyze_feedback(comment),
            "sentiment": "Neutral",
            "competency": "Adequate Competency",
            "recommendation": "Continue monitoring performance.",
            "confidence": 0.0,
        }

    conn = get_db_connection()

    # Try to persist ML artifacts (if columns exist); fallback to legacy schema
    try:
        conn.execute(
            """
            INSERT INTO feedback
            (student_id, supervisor_id, comment, performance_label, ml_prediction, ml_sentiment, ml_competency, ml_recommendation, ml_svm_prediction, ml_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                session["user_id"],
                comment,
                label,
                ml_result.get("performance_label"),
                ml_result.get("sentiment"),
                ml_result.get("competency"),
                ml_result.get("recommendation"),
                ml_result.get("svm_prediction"),
                float(ml_result.get("confidence", 0.0)),
            )
        )
    except Exception:
        # legacy DB without ml columns
        try:
            conn.rollback()
        except Exception:
            pass
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

    try:
        create_notification(
            student_id,
            "New Feedback Received",
            f"Your supervisor left feedback: {comment[:120]}",
            "feedback",
            link_url=f"/student/dashboard",
        )
    except Exception as e:
        print("feedback notification failed:", e)

    return redirect(f"/supervisor/student/{student_id}")

# ---------------- ASSIGN TASK 
@supervisor.route("/supervisor/student/<int:student_id>/assign-task", methods=["GET", "POST"])
@role_required("supervisor")
def assign_task(student_id):
    if not _is_assigned(session.get("user_id"), student_id):
        return "Forbidden — student not assigned to you", 403

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

        task_title = (request.form.get("task_title") or "").strip()
        task_description = (request.form.get("task_description") or "").strip()
        deadline_raw = (request.form.get("deadline") or "").strip()
        deadline = deadline_raw or None
        # Validation — title/description required, student_id is URL param (do not trust form)
        if not task_title or len(task_title) < 3 or len(task_title) > 200:
            flash("Task title is required (3-200 chars).", "danger")
            conn.close()
            return redirect(f"/supervisor/student/{student_id}/assign-task")
        if not task_description or len(task_description) < 5 or len(task_description) > 5000:
            flash("Task description is required (5-5000 chars).", "danger")
            conn.close()
            return redirect(f"/supervisor/student/{student_id}/assign-task")
        if deadline:
            try:
                # Support datetime-local T format and space format
                norm = deadline.replace("T", " ")
                datetime.fromisoformat(norm)
            except:
                try:
                    datetime.strptime(deadline, "%Y-%m-%dT%H:%M")
                except:
                    try:
                        datetime.strptime(deadline, "%Y-%m-%d %H:%M")
                    except:
                        flash("Invalid deadline format.", "danger")
                        conn.close()
                        return redirect(f"/supervisor/student/{student_id}/assign-task")

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

        try:
            create_notification(
                student_id,
                "New Task Assigned",
                f"You have a new task: {task_title}",
                "task",
                link_url="/student/tasks",
            )
        except Exception as e:
            print("task notification failed:", e)

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

        task_title = (request.form.get("task_title") or "").strip()
        task_description = (request.form.get("task_description") or "").strip()
        deadline_raw = (request.form.get("deadline") or "").strip()
        deadline = deadline_raw or None
        if not task_title or len(task_title) < 3 or len(task_title) > 200:
            flash("Task title is required (3-200 chars).", "danger")
            conn.close()
            return redirect(f"/supervisor/task/{task_id}/edit")
        if not task_description or len(task_description) < 5 or len(task_description) > 5000:
            flash("Task description is required (5-5000 chars).", "danger")
            conn.close()
            return redirect(f"/supervisor/task/{task_id}/edit")
        if deadline:
            try:
                norm = deadline.replace("T", " ")
                datetime.fromisoformat(norm)
            except:
                try:
                    datetime.strptime(deadline, "%Y-%m-%dT%H:%M")
                except:
                    try:
                        datetime.strptime(deadline, "%Y-%m-%d %H:%M")
                    except:
                        flash("Invalid deadline format.", "danger")
                        conn.close()
                        return redirect(f"/supervisor/task/{task_id}/edit")

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

        try:
            student_id = task["student_id"] if "student_id" in task.keys() else task[1]
        except:
            try:
                student_id = task[1]
            except:
                student_id = task["student_id"]

        conn.close()

        return redirect(
            f"/supervisor/task/{task_id}"
        )

    try:
        student_id = task["student_id"] if "student_id" in task.keys() else task[1]
    except:
        try:
            student_id = task[1]
        except:
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

# Supervisor document access — secure, ownership-checked
@supervisor.route("/supervisor/document/<int:document_id>")
@role_required("supervisor")
def view_document(document_id):
    conn = get_db_connection()
    try:
        doc = conn.execute("SELECT id, student_id, filename, filepath FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not doc:
            return "Document not found.", 404
        student_id = doc["student_id"] if "student_id" in doc.keys() else doc[1]
        if not _is_assigned(session.get("user_id"), student_id):
            return "Forbidden — student not assigned to you", 403
        filepath = doc["filepath"] if "filepath" in doc.keys() else doc[3]
        filename = doc["filename"] if "filename" in doc.keys() else doc[2]
        # Path traversal protection — must be inside UPLOAD_FOLDER
        upload_base = current_app.config.get("UPLOAD_FOLDER", str(current_app.config.get("UPLOAD_FOLDER", "")))
        if not upload_base:
            from pathlib import Path as _P
            upload_base = str(_P(current_app.root_path).parent / "storage" / "uploads")
        abs_base = os.path.abspath(upload_base)
        abs_target = os.path.abspath(filepath) if filepath else ""
        # Ensure target is inside base and file exists
        if not _is_safe_path(abs_base, abs_target):
            return "Invalid document path.", 403
        if not os.path.exists(abs_target):
            return "Document file missing.", 404
        # MIME check — use send_file with safe filename
        return send_file(abs_target, as_attachment=False, download_name=filename)
    finally:
        conn.close()

@supervisor.route("/supervisor/task/<int:task_id>/submission/<int:submission_id>")
@role_required("supervisor")
def view_task_submission(task_id, submission_id):
    conn = get_db_connection()
    try:
        # Verify task belongs to supervisor
        task = conn.execute("SELECT id, student_id FROM tasks WHERE id = ? AND supervisor_id = ?", (task_id, session.get("user_id"))).fetchone()
        if not task:
            return "Task not found or access denied", 404
        sub = conn.execute("SELECT id, filename, filepath, task_id FROM task_submissions WHERE id = ? AND task_id = ?", (submission_id, task_id)).fetchone()
        if not sub:
            return "Submission not found.", 404
        filepath = sub["filepath"] if "filepath" in sub.keys() else sub[2]
        filename = sub["filename"] if "filename" in sub.keys() else sub[1]
        upload_base = current_app.config.get("UPLOAD_FOLDER", "")
        abs_base = os.path.abspath(upload_base) if upload_base else os.path.abspath(filepath)
        abs_target = os.path.abspath(filepath) if filepath else ""
        if upload_base and not _is_safe_path(abs_base, abs_target):
            return "Invalid submission path.", 403
        if not os.path.exists(abs_target):
            return "Submission file missing.", 404
        return send_file(abs_target, as_attachment=False, download_name=filename)
    finally:
        conn.close()

# Task lifecycle — review / reopen (POST + CSRF + ownership)
@supervisor.route("/supervisor/task/<int:task_id>/review", methods=["POST"])
@role_required("supervisor")
def review_task(task_id):
    conn = get_db_connection()
    try:
        task = conn.execute("SELECT id, student_id, status FROM tasks WHERE id = ? AND supervisor_id = ?", (task_id, session.get("user_id"))).fetchone()
        if not task:
            return "Task not found or access denied", 404
        status = task["status"] if "status" in task.keys() else task[2]
        if status not in ("Submitted", "Pending"):
            flash("Only Submitted tasks can be marked Reviewed.", "warning")
            return redirect(f"/supervisor/task/{task_id}")
        conn.execute("UPDATE tasks SET status = 'Reviewed' WHERE id = ? AND supervisor_id = ?", (task_id, session.get("user_id")))
        conn.commit()
        try:
            sid = task["student_id"] if "student_id" in task.keys() else task[1]
            create_notification(sid, "Task Reviewed", f"Your task has been reviewed.", "task", link_url="/student/tasks")
        except:
            pass
        flash("Task marked as Reviewed.", "success")
        return redirect(f"/supervisor/task/{task_id}")
    finally:
        conn.close()

@supervisor.route("/supervisor/task/<int:task_id>/reopen", methods=["POST"])
@role_required("supervisor")
def reopen_task(task_id):
    conn = get_db_connection()
    try:
        task = conn.execute("SELECT id, student_id, status FROM tasks WHERE id = ? AND supervisor_id = ?", (task_id, session.get("user_id"))).fetchone()
        if not task:
            return "Task not found or access denied", 404
        status = task["status"] if "status" in task.keys() else task[2]
        if status not in ("Submitted", "Reviewed"):
            flash("Only Submitted/Reviewed tasks can be reopened.", "warning")
            return redirect(f"/supervisor/task/{task_id}")
        conn.execute("UPDATE tasks SET status = 'Reopened' WHERE id = ? AND supervisor_id = ?", (task_id, session.get("user_id")))
        conn.commit()
        try:
            sid = task["student_id"] if "student_id" in task.keys() else task[1]
            create_notification(sid, "Task Reopened", f"Your task has been reopened for revision.", "task", link_url="/student/tasks")
        except:
            pass
        flash("Task reopened.", "success")
        return redirect(f"/supervisor/task/{task_id}")
    finally:
        conn.close()