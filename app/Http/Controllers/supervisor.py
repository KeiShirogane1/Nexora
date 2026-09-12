from flask import Blueprint, render_template, request, redirect, session, send_file, current_app, flash, url_for
from app.Http.Middleware.security import role_required
import os
import re
import mimetypes
from app.Models.db import get_db_connection
from datetime import datetime, timedelta
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
    try:
        return _supervisor_dashboard_with_conn(conn)
    finally:
        conn.close()


def _supervisor_dashboard_with_conn(conn):
    cursor = conn.cursor()

    supervisor_id = session["user_id"]

    # Reuse the classroom-first Assigned Interns read model so dashboard
    # summary counts match the rest of the Supervisor portal. Legacy admin
    # assignments remain a compatibility fallback inside the service.
    from app.Services.assigned_interns_service import get_supervisor_assigned_interns

    dashboard_context = get_supervisor_assigned_interns(supervisor_id)
    dashboard_summary = dashboard_context["summary"]
    total_interns = dashboard_summary["total_interns"]
    active_classrooms = dashboard_summary["classroom_count"]
    pending_reviews = dashboard_summary["pending_reviews"]
    dashboard_classrooms = dashboard_context["classrooms"]
    archived_classrooms = sum(1 for classroom in dashboard_classrooms if classroom.get("archived"))

    # Count active attendance sessions. New scoped sessions belong to the
    # supervisor through their Intern Classroom; legacy NULL-scoped sessions
    # keep the previous student_assignments fallback.
    cursor.execute("""
        SELECT COUNT(*)
        FROM attendance a
        WHERE a.status = 'Open'
          AND (
                (
                    a.classroom_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1
                        FROM classrooms c
                        WHERE c.id = a.classroom_id
                          AND c.supervisor_id = ?
                    )
                )
                OR
                (
                    a.classroom_id IS NULL
                    AND EXISTS (
                        SELECT 1
                        FROM student_assignments sa
                        WHERE sa.student_id = a.student_id
                          AND sa.supervisor_id = ?
                    )
                )
          )
    """, (supervisor_id, supervisor_id))

    active_sessions = cursor.fetchone()[0]

    def row_value(row, key, index=0, default=None):
        try:
            if key in row.keys():
                value = row[key]
                return default if value is None else value
        except Exception:
            pass
        try:
            value = row[index]
            return default if value is None else value
        except Exception:
            return default

    def display_name(row, username_index, first_index, last_index):
        first_name = str(row_value(row, "first_name", first_index, "") or "").strip()
        last_name = str(row_value(row, "last_name", last_index, "") or "").strip()
        username = str(row_value(row, "username", username_index, "") or "").strip()
        return " ".join(part for part in (first_name, last_name) if part).strip() or username or "Intern"

    def relative_time(timestamp):
        dt = parse_datetime(timestamp)
        if not dt:
            return "Recently"
        now_for_dt = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        seconds = max(0, int((now_for_dt - dt).total_seconds()))
        if seconds < 60:
            return "Just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} min ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hr{'s' if hours != 1 else ''} ago"
        days = hours // 24
        if days < 7:
            return f"{days} day{'s' if days != 1 else ''} ago"
        return format_datetime(dt)

    # Current classroom-scoped activity feed. These events come from the
    # same Work, Daily OJT, enrollment, and Evaluation data used elsewhere
    # in the Supervisor portal; no legacy student_assignments join is used.
    activity_events = []

    work_submission_rows = cursor.execute("""
        SELECT s.id AS submission_id, s.submitted_at, s.status,
               a.id AS assignment_id, a.title, a.classroom_id,
               c.name AS classroom_name, s.student_id, u.username,
               COALESCE(sp.first_name, '') AS first_name,
               COALESCE(sp.last_name, '') AS last_name
        FROM classwork_submissions s
        JOIN classroom_assignments a ON a.id = s.assignment_id
        JOIN classrooms c ON c.id = a.classroom_id
        JOIN users u ON u.id = s.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = u.id
        WHERE c.supervisor_id = ?
        ORDER BY s.submitted_at DESC, s.id DESC
        LIMIT 6
    """, (supervisor_id,)).fetchall()
    for row in work_submission_rows:
        class_id = int(row_value(row, "classroom_id", 5, 0) or 0)
        assignment_id = int(row_value(row, "assignment_id", 3, 0) or 0)
        submission_id = int(row_value(row, "submission_id", 0, 0) or 0)
        submitted_at = row_value(row, "submitted_at", 1, None)
        activity_events.append({
            "name": display_name(row, 8, 9, 10),
            "message": f"Submitted {row_value(row, 'title', 4, 'Work')} in {row_value(row, 'classroom_name', 6, 'Intern Classroom')}",
            "summary": f"submitted {row_value(row, 'title', 4, 'Work')}",
            "context": row_value(row, "classroom_name", 6, "Intern Classroom"),
            "time": relative_time(submitted_at),
            "timestamp": submitted_at,
            "icon": "↥",
            "tone": "blue",
            "url": url_for(
                "classwork_grading.review",
                class_id=class_id,
                assignment_id=assignment_id,
                submission_id=submission_id,
            ),
            "action_label": "Review Work",
        })

    logbook_rows = cursor.execute("""
        SELECT l.id AS log_id,
               COALESCE(l.updated_at, l.created_at) AS activity_at,
               l.student_id, a.classroom_id, c.name AS classroom_name,
               u.username,
               COALESCE(sp.first_name, '') AS first_name,
               COALESCE(sp.last_name, '') AS last_name
        FROM logs l
        JOIN attendance a ON a.id = l.attendance_id
        JOIN classrooms c ON c.id = a.classroom_id
        JOIN users u ON u.id = l.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = u.id
        WHERE l.entry_type = 'daily'
          AND c.supervisor_id = ?
        ORDER BY COALESCE(l.updated_at, l.created_at) DESC, l.id DESC
        LIMIT 6
    """, (supervisor_id,)).fetchall()
    for row in logbook_rows:
        log_id = int(row_value(row, "log_id", 0, 0) or 0)
        activity_at = row_value(row, "activity_at", 1, None)
        class_id = int(row_value(row, "classroom_id", 3, 0) or 0)
        activity_events.append({
            "name": display_name(row, 5, 6, 7),
            "message": f"Daily OJT Logbook entry in {row_value(row, 'classroom_name', 4, 'Intern Classroom')}",
            "summary": "submitted a logbook entry",
            "context": row_value(row, "classroom_name", 4, "Intern Classroom"),
            "time": relative_time(activity_at),
            "timestamp": activity_at,
            "icon": "▤",
            "tone": "green",
            "url": url_for("logbook_review.supervisor_logbook", class_id=class_id, log_id=log_id),
            "action_label": "Open Logbook",
        })

    join_rows = cursor.execute("""
        SELECT cs.joined_at, cs.student_id, cs.classroom_id,
               c.name AS classroom_name, u.username,
               COALESCE(sp.first_name, '') AS first_name,
               COALESCE(sp.last_name, '') AS last_name
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        JOIN users u ON u.id = cs.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = u.id
        WHERE c.supervisor_id = ?
        ORDER BY cs.joined_at DESC, cs.id DESC
        LIMIT 6
    """, (supervisor_id,)).fetchall()
    for row in join_rows:
        joined_at = row_value(row, "joined_at", 0, None)
        student_id = int(row_value(row, "student_id", 1, 0) or 0)
        class_id = int(row_value(row, "classroom_id", 2, 0) or 0)
        activity_events.append({
            "name": display_name(row, 4, 5, 6),
            "message": f"Joined {row_value(row, 'classroom_name', 3, 'Intern Classroom')}",
            "summary": "joined your classroom",
            "context": row_value(row, "classroom_name", 3, "Intern Classroom"),
            "time": relative_time(joined_at),
            "timestamp": joined_at,
            "icon": "♙",
            "tone": "orange",
            "url": url_for("intern_profile.supervisor_intern_profile", class_id=class_id, student_id=student_id),
            "action_label": "View Intern",
        })

    evaluation_rows = cursor.execute("""
        SELECT e.updated_at, e.status, e.classroom_id, e.student_id,
               c.name AS classroom_name, u.username,
               COALESCE(sp.first_name, '') AS first_name,
               COALESCE(sp.last_name, '') AS last_name
        FROM ojt_evaluations e
        JOIN classrooms c ON c.id = e.classroom_id
        JOIN users u ON u.id = e.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = u.id
        WHERE e.supervisor_id = ?
        ORDER BY e.updated_at DESC, e.id DESC
        LIMIT 6
    """, (supervisor_id,)).fetchall()
    for row in evaluation_rows:
        updated_at = row_value(row, "updated_at", 0, None)
        status = str(row_value(row, "status", 1, "draft") or "draft").strip().lower()
        class_id = int(row_value(row, "classroom_id", 2, 0) or 0)
        student_id = int(row_value(row, "student_id", 3, 0) or 0)
        status_label = "Submitted" if status == "submitted" else "Draft"
        activity_events.append({
            "name": display_name(row, 5, 6, 7),
            "message": f"Official OJT Evaluation {status_label.lower()} in {row_value(row, 'classroom_name', 4, 'Intern Classroom')}",
            "summary": f"has an evaluation {status_label.lower()}",
            "context": row_value(row, "classroom_name", 4, "Intern Classroom"),
            "time": relative_time(updated_at),
            "timestamp": updated_at,
            "icon": "▤",
            "tone": "rose",
            "url": url_for("ojt_evaluation.supervisor_evaluations", class_id=class_id, student_id=student_id),
            "action_label": "Open Evaluation",
        })

    def activity_sort_key(item):
        try:
            dt = parse_datetime(item.get("timestamp"))
            return dt.timestamp() if dt else 0
        except Exception:
            return 0

    activity_events.sort(key=activity_sort_key, reverse=True)
    recent_activity = activity_events[:6]

    # Seven-day activity series for the dashboard chart. Dates are grouped in
    # Python to keep the query portable across SQLite and Postgres.
    now = datetime.now()
    chart_days = [(now - timedelta(days=offset)).date() for offset in range(6, -1, -1)]
    chart_start = datetime.combine(chart_days[0], datetime.min.time())
    chart_index = {day: index for index, day in enumerate(chart_days)}

    def chart_counts(rows, key, index):
        counts = [0] * len(chart_days)
        for row in rows:
            dt = parse_datetime(row_value(row, key, index, None))
            if dt and dt.date() in chart_index:
                counts[chart_index[dt.date()]] += 1
        return counts

    chart_log_rows = cursor.execute("""
        SELECT COALESCE(l.updated_at, l.created_at) AS activity_at
        FROM logs l
        JOIN attendance a ON a.id = l.attendance_id
        JOIN classrooms c ON c.id = a.classroom_id
        WHERE l.entry_type = 'daily'
          AND c.supervisor_id = ?
          AND COALESCE(l.updated_at, l.created_at) >= ?
    """, (supervisor_id, chart_start)).fetchall()

    chart_work_rows = cursor.execute("""
        SELECT s.submitted_at
        FROM classwork_submissions s
        JOIN classroom_assignments a ON a.id = s.assignment_id
        JOIN classrooms c ON c.id = a.classroom_id
        WHERE c.supervisor_id = ?
          AND s.submitted_at >= ?
    """, (supervisor_id, chart_start)).fetchall()

    chart_evaluation_rows = cursor.execute("""
        SELECT COALESCE(e.submitted_at, e.updated_at, e.created_at) AS activity_at
        FROM ojt_evaluations e
        WHERE e.supervisor_id = ?
          AND COALESCE(e.submitted_at, e.updated_at, e.created_at) >= ?
    """, (supervisor_id, chart_start)).fetchall()

    activity_chart = {
        "labels": [f"{day.strftime('%b')} {day.day}" for day in chart_days],
        "logbook": chart_counts(chart_log_rows, "activity_at", 0),
        "work": chart_counts(chart_work_rows, "submitted_at", 0),
        "evaluations": chart_counts(chart_evaluation_rows, "activity_at", 0),
    }

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_interns_this_month = cursor.execute("""
        SELECT COUNT(DISTINCT cs.student_id)
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        WHERE c.supervisor_id = ?
          AND COALESCE(c.archived, 0) = 0
          AND cs.joined_at >= ?
    """, (supervisor_id, month_start)).fetchone()[0]

    upcoming_deadlines = cursor.execute("""
        SELECT COUNT(*)
        FROM classroom_assignments a
        JOIN classrooms c ON c.id = a.classroom_id
        WHERE c.supervisor_id = ?
          AND COALESCE(c.archived, 0) = 0
          AND a.due_at IS NOT NULL
          AND a.due_at >= ?
          AND a.due_at < ?
    """, (supervisor_id, now, now + timedelta(days=7))).fetchone()[0]

    evaluation_drafts = cursor.execute("""
        SELECT COUNT(*)
        FROM ojt_evaluations
        WHERE supervisor_id = ?
          AND status = 'draft'
    """, (supervisor_id,)).fetchone()[0]

    inactivity_cutoff = now - timedelta(days=7)
    classroom_join_rows = cursor.execute("""
        SELECT cs.student_id, MAX(cs.joined_at) AS latest_joined_at
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        WHERE c.supervisor_id = ?
          AND COALESCE(c.archived, 0) = 0
        GROUP BY cs.student_id
    """, (supervisor_id,)).fetchall()

    recent_intern_activity_rows = cursor.execute("""
        SELECT DISTINCT a.student_id
        FROM attendance a
        JOIN classrooms c ON c.id = a.classroom_id
        WHERE c.supervisor_id = ?
          AND COALESCE(c.archived, 0) = 0
          AND a.clock_in >= ?
        UNION
        SELECT DISTINCT l.student_id
        FROM logs l
        JOIN attendance a ON a.id = l.attendance_id
        JOIN classrooms c ON c.id = a.classroom_id
        WHERE c.supervisor_id = ?
          AND COALESCE(c.archived, 0) = 0
          AND COALESCE(l.updated_at, l.created_at) >= ?
        UNION
        SELECT DISTINCT s.student_id
        FROM classwork_submissions s
        JOIN classroom_assignments a ON a.id = s.assignment_id
        JOIN classrooms c ON c.id = a.classroom_id
        WHERE c.supervisor_id = ?
          AND COALESCE(c.archived, 0) = 0
          AND s.submitted_at >= ?
    """, (
        supervisor_id, inactivity_cutoff,
        supervisor_id, inactivity_cutoff,
        supervisor_id, inactivity_cutoff,
    )).fetchall()
    recent_intern_ids = {int(row_value(row, "student_id", 0, 0) or 0) for row in recent_intern_activity_rows}
    inactive_interns = 0
    for row in classroom_join_rows:
        student_id = int(row_value(row, "student_id", 0, 0) or 0)
        joined_at = parse_datetime(row_value(row, "latest_joined_at", 1, None))
        if student_id and joined_at and joined_at < inactivity_cutoff and student_id not in recent_intern_ids:
            inactive_interns += 1

    dashboard_attention = {
        "pending_reviews": int(pending_reviews or 0),
        "upcoming_deadlines": int(upcoming_deadlines or 0),
        "inactive_interns": inactive_interns,
        "evaluation_drafts": int(evaluation_drafts or 0),
    }

    return render_template(
        "supervisor/dashboard.html",
        active_page="dashboard",
        total_interns=total_interns,
        active_classrooms=active_classrooms,
        active_sessions=active_sessions,
        pending_reviews=pending_reviews,
        dashboard_classrooms=dashboard_classrooms,
        recent_activity=recent_activity,
        activity_chart=activity_chart,
        dashboard_attention=dashboard_attention,
        new_interns_this_month=int(new_interns_this_month or 0),
        archived_classrooms=archived_classrooms,
    )

# view interns
@supervisor.route("/supervisor/interns")
@role_required("supervisor")
def view_interns():
    from app.Services.assigned_interns_service import get_supervisor_assigned_interns

    context = get_supervisor_assigned_interns(session["user_id"])
    return render_template(
        "supervisor/interns.html",
        interns=context["interns"],
        summary=context["summary"],
        active_page="interns",
    )


#  View student profile 
@supervisor.route("/supervisor/student/<int:student_id>")
@role_required("supervisor")
def view_student(student_id):
    # Ownership: supervisor may only view assigned students
    if not _is_assigned(session.get("user_id"), student_id):
        return "Forbidden — student not assigned to you", 403
    conn = get_db_connection()
    try:
        # Student info
        student = conn.execute(
            "SELECT username FROM users WHERE id = ?",
            (student_id,)
        ).fetchone()

        if not student:
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
            attendance_row[0],
            format_datetime(attendance_row[1]),
            format_datetime(attendance_row[2]),
            attendance_row[3],
            attendance_row[4]
        )
        for attendance_row in sessions
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
            # legacy DB without ml cols
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
    finally:
        conn.close()


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
    try:
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
            conn.rollback()
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
    except Exception:
        conn.rollback()
        raise
    finally:
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
        current_app.logger.warning("Feedback notification failed: %s", e)

    return redirect(f"/supervisor/student/{student_id}")

# ---------------- ASSIGN TASK 
@supervisor.route("/supervisor/student/<int:student_id>/assign-task", methods=["GET", "POST"])
@role_required("supervisor")
def assign_task(student_id):
    if not _is_assigned(session.get("user_id"), student_id):
        return "Forbidden — student not assigned to you", 403

    conn = get_db_connection()
    task_title = None
    try:
        # Retrieve student information
        student = conn.execute("""
            SELECT username
            FROM users
            WHERE id = ?
        """, (student_id,)).fetchone()

        if not student:
            return "Student not found"

        if request.method != "POST":
            return render_template(
                "supervisor/assign_task.html",
                student=student,
                student_id=student_id,
                active_page="assign_task"
            )

        task_title = (request.form.get("task_title") or "").strip()
        task_description = (request.form.get("task_description") or "").strip()
        deadline_raw = (request.form.get("deadline") or "").strip()
        deadline = deadline_raw or None

        # Validation — title/description required, student_id is URL param (do not trust form)
        if not task_title or len(task_title) < 3 or len(task_title) > 200:
            flash("Task title is required (3-200 chars).", "danger")
            return redirect(f"/supervisor/student/{student_id}/assign-task")
        if not task_description or len(task_description) < 5 or len(task_description) > 5000:
            flash("Task description is required (5-5000 chars).", "danger")
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
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
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
        current_app.logger.warning("Task notification failed: %s", e)

    return redirect(
        f"/supervisor/student/{student_id}"
    )

# View, Edit, Delete, Reopen, and Toggle Tasks #

# View #
@supervisor.route("/supervisor/task/<int:task_id>")
@role_required("supervisor")
def view_task(task_id):
    conn = get_db_connection()
    try:
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
        """, (task_id, session["user_id"])).fetchone()

        if not task:
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

        return render_template(
            "supervisor/view_task.html",
            task=task,
            submissions=submissions,
            active_page="interns"
        )
    finally:
        conn.close()

# Edit #
@supervisor.route("/supervisor/task/<int:task_id>/edit", methods=["GET", "POST"])
@role_required("supervisor")
def edit_task(task_id):
    conn = get_db_connection()
    try:
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
            return "Task not found or access denied", 404

        try:
            student_id = task["student_id"] if "student_id" in task.keys() else task[1]
        except:
            try:
                student_id = task[1]
            except:
                student_id = task["student_id"]

        if request.method != "POST":
            return render_template(
                "supervisor/edit_task.html",
                task=task,
                task_id=task_id,
                student_id=student_id,
                active_page="edit_task"
            )

        task_title = (request.form.get("task_title") or "").strip()
        task_description = (request.form.get("task_description") or "").strip()
        deadline_raw = (request.form.get("deadline") or "").strip()
        deadline = deadline_raw or None

        if not task_title or len(task_title) < 3 or len(task_title) > 200:
            flash("Task title is required (3-200 chars).", "danger")
            return redirect(f"/supervisor/task/{task_id}/edit")
        if not task_description or len(task_description) < 5 or len(task_description) > 5000:
            flash("Task description is required (5-5000 chars).", "danger")
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

        return redirect(
            f"/supervisor/task/{task_id}"
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

# Delete #
@supervisor.route("/supervisor/task/<int:task_id>/delete", methods=["POST"])
@role_required("supervisor")
def delete_task(task_id):
    conn = get_db_connection()
    try:
        task = conn.execute("""
            SELECT student_id
            FROM tasks
            WHERE id = ?
            AND supervisor_id = ?
        """, (task_id, session["user_id"])).fetchone()

        if not task:
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
        return redirect(
            f"/supervisor/student/{student_id}"
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

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
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    try:
        sid = task["student_id"] if "student_id" in task.keys() else task[1]
        create_notification(sid, "Task Reviewed", f"Your task has been reviewed.", "task", link_url="/student/tasks")
    except Exception as e:
        current_app.logger.warning("Task review notification failed: %s", e)

    flash("Task marked as Reviewed.", "success")
    return redirect(f"/supervisor/task/{task_id}")

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
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    try:
        sid = task["student_id"] if "student_id" in task.keys() else task[1]
        create_notification(sid, "Task Reopened", f"Your task has been reopened for revision.", "task", link_url="/student/tasks")
    except Exception as e:
        current_app.logger.warning("Task reopen notification failed: %s", e)

    flash("Task reopened.", "success")
    return redirect(f"/supervisor/task/{task_id}")

@supervisor.route("/supervisor/profile", methods=["GET", "POST"])
@role_required("supervisor")
def supervisor_profile():
    sid = session.get("user_id")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, email, role, status FROM users WHERE id = ?", (sid,))
        user = cur.fetchone()
        if not user:
            flash("Supervisor not found.", "danger")
            return redirect(url_for("supervisor.supervisor_dashboard"))
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            errors = {}
            if not username or len(username) < 3 or not re.match(r"^[A-Za-z0-9_.-]+$", username):
                errors["username"] = "Username must be at least 3 chars, letters/numbers/_.-"
            if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                errors["email"] = "Invalid email"
            cur.execute("SELECT id FROM users WHERE username = ? AND id != ?", (username, sid))
            if cur.fetchone():
                errors["username"] = "Username already exists"
            cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?) AND id != ?", (email, sid))
            if cur.fetchone():
                errors["email"] = "Email already exists"
            if errors:
                for f, m in errors.items():
                    flash(f"{f}: {m}", "danger")
                return render_template("supervisor/profile.html", supervisor=user, active_page="profile")
            cur.execute("UPDATE users SET username = ?, email = ? WHERE id = ?", (username, email, sid))
            conn.commit()
            flash("Profile updated successfully.", "success")
            return redirect(url_for("supervisor.supervisor_profile"))
        return render_template("supervisor/profile.html", supervisor=user, active_page="profile")
    finally:
        try:
            cur.close()
        except:
            pass
        conn.close()