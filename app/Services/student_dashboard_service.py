"""Read-only Student Dashboard data.

Intern Classroom enrollment and classroom Work are authoritative for current OJT
students. Legacy internship/task rows are retained only as a compatibility
fallback for students who have not joined an active Intern Classroom yet.
"""
from datetime import datetime

from app.Models.db import get_db_connection


ACTIVITY_LABELS = {
    "assignment": "Task",
    "google_form": "Form / Assessment",
    "google_doc": "Online Work",
    "file_reference": "Resource",
    "project": "Project",
    "group_project": "Team Task",
}


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
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _format_time(value):
    parsed = _as_datetime(value)
    return parsed.strftime("%I:%M %p").lstrip("0") if parsed else None


def _format_notification_time(value):
    parsed = _as_datetime(value)
    return parsed.strftime("%b %d") if parsed else "Recently"


def _active_classrooms(conn, student_id):
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.name,
            c.section,
            COALESCE(cid.company_name, '') AS company_name,
            COALESCE(NULLIF(cid.internship_title, ''), c.name) AS internship_title,
            u.username AS supervisor_name,
            cid.start_date,
            cid.end_date,
            COALESCE(cid.hours_mode, 'not_specified') AS hours_mode,
            COALESCE(cid.required_hours, 0) AS required_hours,
            COALESCE(cid.work_arrangement, '') AS work_arrangement,
            COALESCE(cid.location, '') AS location,
            cs.joined_at
        FROM classroom_students cs
        JOIN classrooms c ON c.id = cs.classroom_id
        JOIN users u ON u.id = c.supervisor_id
        LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
        WHERE cs.student_id = ?
          AND COALESCE(c.archived, 0) = 0
          AND COALESCE(c.classroom_type, 'classroom') = 'internship'
        ORDER BY cs.joined_at DESC, c.id DESC
        """,
        (student_id,),
    ).fetchall()

    classrooms = []
    for row in rows:
        class_id = int(_value(row, "id", 0, 0) or 0)
        if not class_id:
            continue
        hours_row = conn.execute(
            """
            SELECT COALESCE(SUM(hours_rendered), 0)
            FROM attendance
            WHERE student_id = ?
              AND classroom_id = ?
              AND status = 'Completed'
            """,
            (student_id, class_id),
        ).fetchone()
        completed_hours = float((hours_row[0] if hours_row else 0) or 0)
        hours_mode = str(_value(row, "hours_mode", 8, "not_specified") or "not_specified")
        required_hours_raw = _value(row, "required_hours", 9, 0)
        try:
            required_hours = float(required_hours_raw or 0) if hours_mode == "specified" else 0.0
        except (TypeError, ValueError):
            required_hours = 0.0
        classrooms.append(
            {
                "id": class_id,
                "name": _value(row, "name", 1, "Intern Classroom") or "Intern Classroom",
                "section": _value(row, "section", 2, "") or "",
                "company_name": _value(row, "company_name", 3, "") or "",
                "internship_title": _value(row, "internship_title", 4, "") or "",
                "supervisor_name": _value(row, "supervisor_name", 5, "") or "Supervisor",
                "start_date": _value(row, "start_date", 6, None),
                "end_date": _value(row, "end_date", 7, None),
                "required_hours": required_hours,
                "completed_hours": round(completed_hours, 2),
                "work_arrangement": _value(row, "work_arrangement", 10, "") or "",
                "location": _value(row, "location", 11, "") or "",
                "joined_at": _value(row, "joined_at", 12, None),
            }
        )
    return classrooms


def _legacy_internship(conn, student_id):
    return conn.execute(
        """
        SELECT company_name, position, supervisor_name, start_date, end_date,
               required_hours, completed_hours, status
        FROM internships
        WHERE student_id = ?
        LIMIT 1
        """,
        (student_id,),
    ).fetchone()


def _work_access_sql():
    return """
        FROM classroom_assignments a
        JOIN classrooms c ON c.id = a.classroom_id
        JOIN classroom_students cs
          ON cs.classroom_id = c.id
         AND cs.student_id = ?
        LEFT JOIN classroom_assignment_meta m ON m.assignment_id = a.id
        WHERE COALESCE(c.archived, 0) = 0
          AND COALESCE(c.classroom_type, 'classroom') = 'internship'
          AND (
              NOT EXISTS (
                  SELECT 1
                  FROM classroom_assignment_recipients all_recipients
                  WHERE all_recipients.assignment_id = a.id
              )
              OR EXISTS (
                  SELECT 1
                  FROM classroom_assignment_recipients my_recipient
                  WHERE my_recipient.assignment_id = a.id
                    AND my_recipient.student_id = ?
              )
          )
    """


def _modern_work(conn, student_id):
    access_sql = _work_access_sql()
    summary = conn.execute(
        """
        SELECT
            COUNT(*) AS total_count,
            COALESCE(SUM(
                CASE WHEN
                    (
                        COALESCE(m.submission_mode, 'individual') = 'shared'
                        AND EXISTS (
                            SELECT 1
                            FROM classwork_submissions s
                            WHERE s.assignment_id = a.id
                              AND COALESCE(s.is_team_submission, 0) = 1
                        )
                    )
                    OR
                    (
                        COALESCE(m.submission_mode, 'individual') <> 'shared'
                        AND (
                            EXISTS (
                                SELECT 1
                                FROM classwork_submissions s
                                WHERE s.assignment_id = a.id
                                  AND s.student_id = ?
                                  AND COALESCE(s.is_team_submission, 0) = 0
                            )
                            OR EXISTS (
                                SELECT 1
                                FROM classroom_submissions legacy_s
                                WHERE legacy_s.assignment_id = a.id
                                  AND legacy_s.student_id = ?
                            )
                        )
                    )
                    THEN 1 ELSE 0
                END
            ), 0) AS submitted_count
        """ + access_sql,
        (student_id, student_id, student_id, student_id),
    ).fetchone()

    rows = conn.execute(
        """
        SELECT
            a.id,
            a.classroom_id,
            a.title,
            a.due_at,
            a.created_at,
            c.name AS classroom_name,
            COALESCE(m.activity_type, 'assignment') AS activity_type,
            COALESCE(m.submission_mode, 'individual') AS submission_mode,
            CASE WHEN
                (
                    COALESCE(m.submission_mode, 'individual') = 'shared'
                    AND EXISTS (
                        SELECT 1
                        FROM classwork_submissions s
                        WHERE s.assignment_id = a.id
                          AND COALESCE(s.is_team_submission, 0) = 1
                    )
                )
                OR
                (
                    COALESCE(m.submission_mode, 'individual') <> 'shared'
                    AND (
                        EXISTS (
                            SELECT 1
                            FROM classwork_submissions s
                            WHERE s.assignment_id = a.id
                              AND s.student_id = ?
                              AND COALESCE(s.is_team_submission, 0) = 0
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM classroom_submissions legacy_s
                            WHERE legacy_s.assignment_id = a.id
                              AND legacy_s.student_id = ?
                        )
                    )
                )
                THEN 1 ELSE 0
            END AS is_submitted
        """ + access_sql + """
        ORDER BY
            CASE WHEN a.due_at IS NULL THEN 1 ELSE 0 END,
            a.due_at ASC,
            a.created_at DESC,
            a.id DESC
        LIMIT 5
        """,
        (student_id, student_id, student_id, student_id),
    ).fetchall()

    now = datetime.now()
    items = []
    for row in rows:
        due_at = _value(row, "due_at", 3, None)
        is_submitted = bool(_value(row, "is_submitted", 8, 0))
        status = "Submitted" if is_submitted else "Pending"
        due_dt = _as_datetime(due_at)
        if not is_submitted and due_dt:
            compare_now = datetime.now(due_dt.tzinfo) if due_dt.tzinfo else now
            if due_dt < compare_now:
                status = "Overdue"
        activity_type = str(_value(row, "activity_type", 6, "assignment") or "assignment")
        class_id = int(_value(row, "classroom_id", 1, 0) or 0)
        assignment_id = int(_value(row, "id", 0, 0) or 0)
        items.append(
            {
                "id": assignment_id,
                "class_id": class_id,
                "title": _value(row, "title", 2, "Work") or "Work",
                "due_at": due_at,
                "created_at": _value(row, "created_at", 4, None),
                "classroom_name": _value(row, "classroom_name", 5, "Intern Classroom") or "Intern Classroom",
                "activity_type": activity_type,
                "activity_label": ACTIVITY_LABELS.get(activity_type, "Work"),
                "status": status,
                "url": f"/student/classes/{class_id}/classwork/{assignment_id}",
            }
        )

    return int(_value(summary, "total_count", 0, 0) or 0), int(
        _value(summary, "submitted_count", 1, 0) or 0
    ), items


def _legacy_work(conn, student_id):
    total_row = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE student_id = ?",
        (student_id,),
    ).fetchone()
    submitted_row = conn.execute(
        """
        SELECT COUNT(*)
        FROM tasks
        WHERE student_id = ? AND status IN ('Submitted', 'Reviewed')
        """,
        (student_id,),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT id, task_title, assigned_at, deadline, status
        FROM tasks
        WHERE student_id = ?
        ORDER BY assigned_at DESC, id DESC
        LIMIT 5
        """,
        (student_id,),
    ).fetchall()
    items = [
        {
            "id": int(_value(row, "id", 0, 0) or 0),
            "class_id": None,
            "title": _value(row, "task_title", 1, "Task") or "Task",
            "due_at": _value(row, "deadline", 3, None),
            "created_at": _value(row, "assigned_at", 2, None),
            "classroom_name": "Legacy assignment",
            "activity_type": "assignment",
            "activity_label": "Task",
            "status": _value(row, "status", 4, "Pending") or "Pending",
            "url": f"/student/task/{int(_value(row, 'id', 0, 0) or 0)}",
        }
        for row in rows
    ]
    return int((total_row[0] if total_row else 0) or 0), int(
        (submitted_row[0] if submitted_row else 0) or 0
    ), items


def _scoped_logbook(conn, student_id):
    rows = conn.execute(
        """
        SELECT
            l.id,
            l.content,
            COALESCE(l.updated_at, l.created_at) AS activity_at,
            c.id AS classroom_id,
            c.name AS classroom_name,
            a.status AS attendance_status,
            COALESCE(lr.status, 'pending') AS review_status
        FROM logs l
        JOIN attendance a ON a.id = l.attendance_id
        JOIN classrooms c ON c.id = a.classroom_id
        JOIN classroom_students cs
          ON cs.classroom_id = c.id
         AND cs.student_id = l.student_id
        LEFT JOIN logbook_reviews lr ON lr.log_id = l.id
        WHERE l.student_id = ?
          AND COALESCE(l.entry_type, 'daily') = 'daily'
          AND COALESCE(c.archived, 0) = 0
          AND COALESCE(c.classroom_type, 'classroom') = 'internship'
        ORDER BY COALESCE(l.updated_at, l.created_at) DESC, l.id DESC
        LIMIT 5
        """,
        (student_id,),
    ).fetchall()

    count_row = conn.execute(
        """
        SELECT
            COUNT(*) AS log_count,
            COALESCE(SUM(CASE
                WHEN a.status <> 'Open' AND COALESCE(lr.status, 'pending') = 'pending'
                THEN 1 ELSE 0 END), 0) AS pending_count,
            COALESCE(SUM(CASE
                WHEN COALESCE(lr.status, '') = 'revision_requested'
                THEN 1 ELSE 0 END), 0) AS revision_count
        FROM logs l
        JOIN attendance a ON a.id = l.attendance_id
        JOIN classrooms c ON c.id = a.classroom_id
        JOIN classroom_students cs
          ON cs.classroom_id = c.id
         AND cs.student_id = l.student_id
        LEFT JOIN logbook_reviews lr ON lr.log_id = l.id
        WHERE l.student_id = ?
          AND COALESCE(l.entry_type, 'daily') = 'daily'
          AND COALESCE(c.archived, 0) = 0
          AND COALESCE(c.classroom_type, 'classroom') = 'internship'
        """,
        (student_id,),
    ).fetchone()

    labels = {
        "pending": "Pending Review",
        "reviewed": "Reviewed",
        "approved": "Reviewed",
        "revision_requested": "Revision Requested",
    }
    recent = []
    for row in rows:
        review_status = str(_value(row, "review_status", 6, "pending") or "pending").lower()
        attendance_status = str(_value(row, "attendance_status", 5, "") or "")
        if attendance_status == "Open":
            review_status = "in_progress"
            review_label = "In Progress"
        else:
            review_label = labels.get(review_status, review_status.replace("_", " ").title())
        log_id = int(_value(row, "id", 0, 0) or 0)
        recent.append(
            {
                "id": log_id,
                "content": _value(row, "content", 1, "Logbook entry") or "Logbook entry",
                "created_at": _value(row, "activity_at", 2, None),
                "classroom_id": int(_value(row, "classroom_id", 3, 0) or 0),
                "classroom_name": _value(row, "classroom_name", 4, "Intern Classroom") or "Intern Classroom",
                "review_status": review_status,
                "review_label": review_label,
                "url": f"/student/daily-log/{log_id}/review" if attendance_status != "Open" else "/student/logbook",
            }
        )

    return (
        int(_value(count_row, "log_count", 0, 0) or 0),
        {
            "pending": int(_value(count_row, "pending_count", 1, 0) or 0),
            "revision_requested": int(_value(count_row, "revision_count", 2, 0) or 0),
        },
        recent,
    )


def _legacy_logbook(conn, student_id):
    count_row = conn.execute(
        "SELECT COUNT(*) FROM logs WHERE student_id = ?",
        (student_id,),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT id, content, created_at
        FROM logs
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (student_id,),
    ).fetchall()
    recent = [
        {
            "id": int(_value(row, "id", 0, 0) or 0),
            "content": _value(row, "content", 1, "Logbook entry") or "Logbook entry",
            "created_at": _value(row, "created_at", 2, None),
            "classroom_id": None,
            "classroom_name": "Legacy OJT record",
            "review_status": "recorded",
            "review_label": "Recorded",
            "url": "/student/logbook",
        }
        for row in rows
    ]
    return int((count_row[0] if count_row else 0) or 0), {"pending": 0, "revision_requested": 0}, recent


def get_student_dashboard_context(student_id):
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return {"profile_ready": False}

    conn = get_db_connection()
    try:
        profile = conn.execute(
            """
            SELECT first_name, middle_name, last_name, age, student_id,
                   profile_picture, phone_number, home_address, grade_year, major_program
            FROM student_profiles
            WHERE user_id = ?
            """,
            (student_id,),
        ).fetchone()
        profile_ready = bool(profile and _value(profile, "grade_year", 8, None) is not None)
        if not profile_ready:
            return {"profile_ready": False, "profile": profile}

        classrooms = _active_classrooms(conn, student_id)
        has_current_classroom = bool(classrooms)

        if has_current_classroom:
            primary = classrooms[0]
            internship = (
                primary["company_name"] or primary["name"],
                primary["internship_title"] or primary["name"],
                primary["supervisor_name"],
                primary["start_date"],
                primary["end_date"],
                primary["required_hours"],
                primary["completed_hours"],
                "Active",
            )
            task_total, task_completed, recent_tasks = _modern_work(conn, student_id)
            log_count, logbook_review_status, recent_logs = _scoped_logbook(conn, student_id)
            attendance_row = conn.execute(
                """
                SELECT COUNT(*)
                FROM attendance a
                JOIN classrooms c ON c.id = a.classroom_id
                JOIN classroom_students cs
                  ON cs.classroom_id = c.id
                 AND cs.student_id = a.student_id
                WHERE a.student_id = ?
                  AND a.status = 'Completed'
                  AND COALESCE(c.archived, 0) = 0
                  AND COALESCE(c.classroom_type, 'classroom') = 'internship'
                """,
                (student_id,),
            ).fetchone()
            attendance_count = int((attendance_row[0] if attendance_row else 0) or 0)
        else:
            internship = _legacy_internship(conn, student_id)
            task_total, task_completed, recent_tasks = _legacy_work(conn, student_id)
            log_count, logbook_review_status, recent_logs = _legacy_logbook(conn, student_id)
            attendance_row = conn.execute(
                "SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Completed'",
                (student_id,),
            ).fetchone()
            attendance_count = int((attendance_row[0] if attendance_row else 0) or 0)

        open_row = conn.execute(
            """
            SELECT a.id, a.classroom_id, a.clock_in, c.name AS classroom_name
            FROM attendance a
            LEFT JOIN classrooms c ON c.id = a.classroom_id
            WHERE a.student_id = ? AND a.status = 'Open'
            ORDER BY a.clock_in DESC
            LIMIT 1
            """,
            (student_id,),
        ).fetchone()
        open_attendance = None
        if open_row:
            open_attendance = {
                "id": int(_value(open_row, "id", 0, 0) or 0),
                "classroom_id": _value(open_row, "classroom_id", 1, None),
                "clock_in": _format_time(_value(open_row, "clock_in", 2, None)) or "Recently",
                "clock_in_raw": _value(open_row, "clock_in", 2, None),
                "classroom_name": _value(open_row, "classroom_name", 3, "") or "OJT session",
            }

        performance_row = conn.execute(
            """
            SELECT AVG(dpr.percentage) AS average_percentage,
                   AVG(dpr.star_rating) AS average_star,
                   COUNT(*) AS rated_days
            FROM daily_performance_ratings dpr
            JOIN attendance a ON a.id = dpr.attendance_id
            LEFT JOIN classrooms c ON c.id = a.classroom_id
            WHERE a.student_id = ?
              AND (
                    (a.classroom_id IS NOT NULL
                     AND COALESCE(c.archived, 0) = 0
                     AND COALESCE(c.classroom_type, 'classroom') = 'internship')
                    OR
                    (a.classroom_id IS NULL AND ? = 0)
              )
            """,
            (student_id, 1 if has_current_classroom else 0),
        ).fetchone()
        avg_percentage = _value(performance_row, "average_percentage", 0, None)
        avg_star = _value(performance_row, "average_star", 1, None)
        dashboard_performance = {
            "average_percentage": round(float(avg_percentage), 1) if avg_percentage is not None else None,
            "average_star": round(float(avg_star), 1) if avg_star is not None else None,
            "rated_days": int(_value(performance_row, "rated_days", 2, 0) or 0),
        }

        document_count_row = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        document_count = int((document_count_row[0] if document_count_row else 0) or 0)
        recent_documents = conn.execute(
            """
            SELECT id, filename, uploaded_at
            FROM documents
            WHERE student_id = ?
            ORDER BY uploaded_at DESC, id DESC
            LIMIT 5
            """,
            (student_id,),
        ).fetchall()
        recent_attendance = conn.execute(
            """
            SELECT id, classroom_id, clock_in, clock_out, hours_rendered, status
            FROM attendance
            WHERE student_id = ?
            ORDER BY clock_in DESC, id DESC
            LIMIT 5
            """,
            (student_id,),
        ).fetchall()

        return {
            "profile_ready": True,
            "profile": profile,
            "internship": internship,
            "log_count": log_count,
            "task_total": task_total,
            "task_completed": task_completed,
            "document_count": document_count,
            "attendance_count": attendance_count,
            "recent_logs": recent_logs,
            "recent_tasks": recent_tasks,
            "recent_documents": recent_documents,
            "recent_attendance": recent_attendance,
            "dashboard_classrooms": classrooms,
            "open_attendance": open_attendance,
            "logbook_review_status": logbook_review_status,
            "dashboard_performance": dashboard_performance,
            # No fake competency percentages. Add only rubric-backed values later.
            "dashboard_competencies": [],
        }
    finally:
        conn.close()
