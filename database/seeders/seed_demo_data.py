"""Seed one complete Nexora demo classroom with five students.

Run manually with:
    python database/seeders/seed_demo_data.py

The five demo students share one classroom. The seeder does not change the
schema and reuses named demo records when they already exist.
"""
from datetime import datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.Models.db import get_db_connection
from app.Services.password_security import hash_password
from app.Services.classroom_service import ensure_classroom_schema
from app.Services.classwork_score_schema import ensure_classwork_score_schema
from app.Services.performance_rating_service import ensure_daily_performance_rating_schema
from app.Services.attendance_service import ensure_attendance_schema
from app.Services.logbook_service import ensure_logbook_schema
from app.Services.ojt_evaluation_service import ensure_ojt_evaluation_schema
from scripts.init_db import initialize_database

SEED_COUNT = 5
PASSWORD = "NexoraDemo123!"
SUPERVISOR_USERNAME = "demo_supervisor"
CLASSROOM_NAME = "Demo Classroom 1"
CLASSROOM_CODE = "DMO126"


def get_id(conn, table, where_sql, params):
    row = conn.execute(f"SELECT id FROM {table} WHERE {where_sql} LIMIT 1", params).fetchone()
    return row[0] if row else None


def ensure_user(conn, username, email, role):
    user_id = get_id(conn, "users", "username = ?", (username,))
    if user_id:
        return user_id
    conn.execute(
        "INSERT INTO users (username, email, password, role, status, password_changed_at) VALUES (?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)",
        (username, email, hash_password(PASSWORD), role),
    )
    return get_id(conn, "users", "username = ?", (username,))


def ensure_profile(conn, user_id, index):
    if get_id(conn, "student_profiles", "user_id = ?", (user_id,)):
        return
    conn.execute(
        """INSERT INTO student_profiles
        (user_id, first_name, middle_name, last_name, age, student_id, school_email,
         phone_number, home_address, grade_year, major_program, emergency_name,
         emergency_relationship, emergency_phone, emergency_email, profile_completed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (
            user_id, f"Demo{index}", "M.", f"Student{index}", 20 + index % 3,
            f"DEMO-2026-{index:03d}", f"demo{index}@nexora.test", f"091700000{index}",
            f"Demo Address {index}", "4th Year", "Information Technology",
            f"Emergency Contact {index}", "Parent", f"091800000{index}",
            f"emergency{index}@nexora.test",
        ),
    )


def ensure_classroom(conn, supervisor_id):
    classroom_id = get_id(
        conn,
        "classrooms",
        "name = ? AND supervisor_id = ?",
        (CLASSROOM_NAME, supervisor_id),
    )
    if classroom_id:
        return classroom_id
    conn.execute(
        """INSERT INTO classrooms
        (supervisor_id, name, section, description, code, classroom_type, banner_theme, archived)
        VALUES (?, ?, 'BSIT-1', ?, ?, 'classroom', 'blue', 0)""",
        (
            supervisor_id,
            CLASSROOM_NAME,
            "Complete demo classroom with five students and sample Gradebook, attendance, logbook, and performance data.",
            CLASSROOM_CODE,
        ),
    )
    return get_id(conn, "classrooms", "code = ?", (CLASSROOM_CODE,))


def ensure_assignment(conn, classroom_id, supervisor_id, index):
    title = f"Demo Classwork {index}"
    assignment_id = get_id(
        conn,
        "classroom_assignments",
        "classroom_id = ? AND title = ?",
        (classroom_id, title),
    )
    if assignment_id:
        return assignment_id
    due_at = datetime.now() - timedelta(days=6 - index)
    conn.execute(
        """INSERT INTO classroom_assignments
        (classroom_id, author_id, title, description, due_at, points)
        VALUES (?, ?, ?, ?, ?, 100)""",
        (
            classroom_id,
            supervisor_id,
            title,
            f"Graded classroom activity {index}: practical work, documentation, and reflection.",
            due_at,
        ),
    )
    return get_id(conn, "classroom_assignments", "classroom_id = ? AND title = ?", (classroom_id, title))


def seed_classwork(conn, classroom_id, student_id, student_index, assignment_ids):
    for assignment_index, assignment_id in enumerate(assignment_ids, 1):
        score = min(100, 70 + student_index * 4 + assignment_index * 2)
        submission = conn.execute(
            "SELECT id FROM classroom_submissions WHERE assignment_id = ? AND student_id = ? LIMIT 1",
            (assignment_id, student_id),
        ).fetchone()
        if not submission:
            conn.execute(
                """INSERT INTO classroom_submissions
                (assignment_id, student_id, content, filename, filepath, status, grade, feedback)
                VALUES (?, ?, ?, ?, ?, 'graded', ?, ?)""",
                (
                    assignment_id,
                    student_id,
                    f"Demo submission by Student {student_index} for Classwork {assignment_index}.",
                    f"demo_student{student_index}_classwork{assignment_index}.txt",
                    f"seed/demo_student{student_index}_classwork{assignment_index}.txt",
                    str(score),
                    f"Graded sample submission for Student {student_index}.",
                ),
            )
        existing_score = conn.execute(
            "SELECT id FROM classwork_scores WHERE assignment_id = ? AND student_id = ? LIMIT 1",
            (assignment_id, student_id),
        ).fetchone()
        if not existing_score:
            conn.execute(
                """INSERT INTO classwork_scores
                (assignment_id, student_id, score, max_score, percentage, grading_method)
                VALUES (?, ?, ?, 100, ?, 'seeded')""",
                (assignment_id, student_id, score, score),
            )


def seed_student(conn, classroom_id, supervisor_id, student_id, index):
    conn.execute(
        "INSERT INTO student_assignments (student_id, supervisor_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
        (student_id, supervisor_id),
    )
    conn.execute(
        "INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
        (classroom_id, student_id),
    )

    task_title = f"Demo Student Task {index}"
    task_id = get_id(conn, "tasks", "student_id = ? AND task_title = ?", (student_id, task_title))
    if not task_id:
        conn.execute(
            """INSERT INTO tasks
            (student_id, supervisor_id, task_title, task_description, assigned_at, deadline,
             requires_submission, allow_late_submission, status)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, 'Completed')""",
            (
                student_id,
                supervisor_id,
                task_title,
                f"Practical demo task for Student {index}.",
                datetime.now() - timedelta(days=15),
                datetime.now() - timedelta(days=8),
            ),
        )
        task_id = get_id(conn, "tasks", "student_id = ? AND task_title = ?", (student_id, task_title))
    if not conn.execute("SELECT id FROM task_submissions WHERE task_id = ? LIMIT 1", (task_id,)).fetchone():
        conn.execute(
            "INSERT INTO task_submissions (task_id, filename, filepath, remarks) VALUES (?, ?, ?, ?)",
            (task_id, f"demo_task_{index}.txt", f"seed/demo_task_{index}.txt", "Completed demo task submission."),
        )

    for day_index in range(1, 6):
        day = datetime.now() - timedelta(days=20 - day_index - index)
        attendance = conn.execute(
            "SELECT id FROM attendance WHERE classroom_id = ? AND student_id = ? AND date(clock_in) = date(?) LIMIT 1",
            (classroom_id, student_id, day),
        ).fetchone()
        if attendance:
            attendance_id = attendance[0]
        else:
            hours = 7.5 + ((index + day_index) % 2) * 0.5
            conn.execute(
                """INSERT INTO attendance
                (student_id, classroom_id, clock_in, clock_out, hours_rendered, status)
                VALUES (?, ?, ?, ?, ?, 'Completed')""",
                (
                    student_id,
                    classroom_id,
                    day.replace(hour=8, minute=0, second=0, microsecond=0),
                    day.replace(hour=17, minute=0, second=0, microsecond=0),
                    hours,
                ),
            )
            attendance = conn.execute(
                "SELECT id FROM attendance WHERE classroom_id = ? AND student_id = ? AND date(clock_in) = date(?) LIMIT 1",
                (classroom_id, student_id, day),
            ).fetchone()
            attendance_id = attendance[0]

        if not conn.execute("SELECT id FROM logs WHERE attendance_id = ? AND student_id = ? AND entry_type = 'daily' LIMIT 1", (attendance_id, student_id)).fetchone():
            conn.execute(
                """INSERT INTO logs (attendance_id, student_id, content, created_at, entry_type)
                VALUES (?, ?, ?, ?, 'daily')""",
                (
                    attendance_id,
                    student_id,
                    f"Day {day_index}: Student {index} completed classroom activities, documented progress, and reviewed feedback.",
                    day.replace(hour=17, minute=5),
                ),
            )

        if not conn.execute("SELECT id FROM daily_performance_ratings WHERE attendance_id = ? AND supervisor_id = ? LIMIT 1", (attendance_id, supervisor_id)).fetchone():
            star = min(5.0, 3.0 + index * 0.25 + day_index * 0.08)
            pct = min(100.0, 74.0 + index * 3.0 + day_index * 2.0)
            conn.execute(
                """INSERT INTO daily_performance_ratings
                (attendance_id, supervisor_id, star_rating, percentage, comment)
                VALUES (?, ?, ?, ?, ?)""",
                (attendance_id, supervisor_id, round(star, 1), round(pct, 1), f"Student {index} performance rating for day {day_index}."),
            )

    if not conn.execute("SELECT id FROM feedback WHERE student_id = ? AND supervisor_id = ? LIMIT 1", (student_id, supervisor_id)).fetchone():
        label = "Excellent" if index >= 4 else "Good"
        conn.execute(
            """INSERT INTO feedback
            (student_id, supervisor_id, comment, performance_label, ml_prediction, ml_sentiment,
             ml_competency, ml_recommendation, ml_svm_prediction, ml_confidence)
            VALUES (?, ?, ?, ?, ?, 'positive', 'Technical Skills', ?, ?, ?)""",
            (
                student_id,
                supervisor_id,
                f"Student {index} shows consistent participation and measurable progress.",
                label,
                label,
                "Continue improving practical skills and documentation quality.",
                label,
                min(0.98, 0.78 + index * 0.035),
            ),
        )

    if not conn.execute("SELECT id FROM notifications WHERE user_id = ? AND title = 'Demo classroom ready' LIMIT 1", (student_id,)).fetchone():
        conn.execute(
            """INSERT INTO notifications
            (user_id, title, message, notification_type, is_read, link_url)
            VALUES (?, 'Demo classroom ready', ?, 'info', 0, '/student/dashboard')""",
            (student_id, "You are assigned to the demo classroom with complete sample data."),
        )


def main():
    initialize_database()
    ensure_classroom_schema()
    ensure_classwork_score_schema()
    ensure_daily_performance_rating_schema()
    ensure_attendance_schema()
    ensure_logbook_schema()
    ensure_ojt_evaluation_schema()

    conn = get_db_connection()
    try:
        supervisor_id = ensure_user(conn, SUPERVISOR_USERNAME, "demo.supervisor@nexora.test", "supervisor")
        classroom_id = ensure_classroom(conn, supervisor_id)
        assignment_ids = [ensure_assignment(conn, classroom_id, supervisor_id, i) for i in range(1, 6)]

        for index in range(1, SEED_COUNT + 1):
            student_id = ensure_user(conn, f"demo_student{index}", f"demo.student{index}@nexora.test", "student")
            ensure_profile(conn, student_id, index)
            seed_student(conn, classroom_id, supervisor_id, student_id, index)
            seed_classwork(conn, classroom_id, student_id, index, assignment_ids)

        conn.commit()
        print(f"Seeded one classroom with {SEED_COUNT} students and complete connected demo data.")
        print(f"Classroom: {CLASSROOM_NAME} ({CLASSROOM_CODE})")
        print(f"Demo supervisor: {SUPERVISOR_USERNAME}")
        print(f"Demo password: {PASSWORD}")
        print("Demo students: demo_student1 through demo_student5")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
