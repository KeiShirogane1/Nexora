"""Seed five complete Nexora demo data sets.

Run manually with:
    python database/seeders/seed_demo_data.py

The seeder is intentionally idempotent: rerunning it reuses the five named
records instead of creating duplicates. It does not change the database schema.
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


def row_id(conn, table, key, value):
    row = conn.execute(f"SELECT id FROM {table} WHERE {key} = ? LIMIT 1", (value,)).fetchone()
    return row[0] if row else None


def ensure_user(conn, username, email, role):
    existing = conn.execute("SELECT id FROM users WHERE username = ? LIMIT 1", (username,)).fetchone()
    if existing:
        return existing[0]
    conn.execute(
        "INSERT INTO users (username, email, password, role, status, password_changed_at) VALUES (?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)",
        (username, email, hash_password(PASSWORD), role),
    )
    return row_id(conn, "users", "username", username)


def ensure_student_profile(conn, user_id, index):
    student_no = f"DEMO-2026-{index:03d}"
    existing = conn.execute("SELECT id FROM student_profiles WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
    if existing:
        return existing[0]
    conn.execute(
        """INSERT INTO student_profiles
        (user_id, first_name, middle_name, last_name, age, student_id, school_email,
         phone_number, home_address, grade_year, major_program, emergency_name,
         emergency_relationship, emergency_phone, emergency_email, profile_completed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (
            user_id, f"Demo{index}", "M.", f"Student{index}", 20 + (index % 3), student_no,
            f"demo{index}@nexora.test", f"091700000{index}", f"Demo Address {index}",
            "4th Year", "Information Technology", f"Emergency Contact {index}",
            "Parent", f"091800000{index}", f"emergency{index}@nexora.test",
        ),
    )
    return row_id(conn, "student_profiles", "user_id", user_id)


def ensure_classroom(conn, supervisor_id, index, classroom_type="classroom"):
    name = f"Demo Classroom {index}"
    existing = conn.execute("SELECT id FROM classrooms WHERE name = ? AND supervisor_id = ? LIMIT 1", (name, supervisor_id)).fetchone()
    if existing:
        return existing[0]
    code = f"DMO{index}26"
    conn.execute(
        """INSERT INTO classrooms
        (supervisor_id, name, section, description, code, classroom_type, banner_theme, archived)
        VALUES (?, ?, ?, ?, ?, ?, 'blue', 0)""",
        (supervisor_id, name, f"BSIT-{index}", f"Demo dataset {index} for Nexora dashboards and reports.", code, classroom_type),
    )
    return row_id(conn, "classrooms", "code", code)


def seed_one(conn, supervisor_id, index):
    username = f"demo_student{index}"
    student_id = ensure_user(conn, username, f"demo.student{index}@nexora.test", "student")
    ensure_student_profile(conn, student_id, index)

    classroom_type = "internship" if index % 2 == 0 else "classroom"
    classroom_id = ensure_classroom(conn, supervisor_id, index, classroom_type)

    conn.execute(
        "INSERT INTO student_assignments (student_id, supervisor_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
        (student_id, supervisor_id),
    )
    conn.execute(
        "INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
        (classroom_id, student_id),
    )

    task_title = f"Demo Task {index}"
    task = conn.execute("SELECT id FROM tasks WHERE student_id = ? AND task_title = ? LIMIT 1", (student_id, task_title)).fetchone()
    if task:
        task_id = task[0]
    else:
        conn.execute(
            """INSERT INTO tasks
            (student_id, supervisor_id, task_title, task_description, assigned_at, deadline,
             requires_submission, allow_late_submission, status)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, 'Completed')""",
            (student_id, supervisor_id, task_title, f"Complete demo activity {index}.", datetime.now() - timedelta(days=7), datetime.now() - timedelta(days=1)),
        )
        task = conn.execute("SELECT id FROM tasks WHERE student_id = ? AND task_title = ? LIMIT 1", (student_id, task_title)).fetchone()
        task_id = task[0]
    conn.execute(
        "INSERT INTO task_submissions (task_id, filename, filepath, remarks) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (task_id, f"demo_submission_{index}.txt", f"seed/demo_submission_{index}.txt", "Demo seed submission."),
    )

    assignment_title = f"Demo Classwork {index}"
    assignment = conn.execute("SELECT id FROM classroom_assignments WHERE classroom_id = ? AND title = ? LIMIT 1", (classroom_id, assignment_title)).fetchone()
    if assignment:
        assignment_id = assignment[0]
    else:
        conn.execute(
            "INSERT INTO classroom_assignments (classroom_id, author_id, title, description, due_at, points) VALUES (?, ?, ?, ?, ?, 100)",
            (classroom_id, supervisor_id, assignment_title, f"Demo graded activity {index}.", datetime.now() - timedelta(days=2)),
        )
        assignment = conn.execute("SELECT id FROM classroom_assignments WHERE classroom_id = ? AND title = ? LIMIT 1", (classroom_id, assignment_title)).fetchone()
        assignment_id = assignment[0]
    conn.execute(
        "INSERT INTO classroom_submissions (assignment_id, student_id, content, filename, filepath, status, grade, feedback) VALUES (?, ?, ?, ?, ?, 'graded', ?, ?) ON CONFLICT DO NOTHING",
        (assignment_id, student_id, f"Demo answer {index}", f"demo_answer_{index}.txt", f"seed/demo_answer_{index}.txt", str(78 + index * 3), "Demo grading feedback."),
    )
    score = min(100, 78 + index * 3)
    conn.execute(
        "INSERT INTO classwork_scores (assignment_id, student_id, score, max_score, percentage, grading_method) VALUES (?, ?, ?, 100, ?, 'seeded') ON CONFLICT DO NOTHING",
        (assignment_id, student_id, score, score),
    )

    day = datetime.now() - timedelta(days=10 - index)
    attendance = conn.execute(
        "SELECT id FROM attendance WHERE student_id = ? AND date(clock_in) = date(?) LIMIT 1",
        (student_id, day),
    ).fetchone()
    if attendance:
        attendance_id = attendance[0]
    else:
        clock_in = day.replace(hour=8, minute=0, second=0, microsecond=0)
        clock_out = day.replace(hour=17, minute=0, second=0, microsecond=0)
        conn.execute(
            "INSERT INTO attendance (student_id, classroom_id, clock_in, clock_out, hours_rendered, status) VALUES (?, ?, ?, ?, 8.0, 'Completed')",
            (student_id, classroom_id, clock_in, clock_out),
        )
        attendance = conn.execute(
            "SELECT id FROM attendance WHERE student_id = ? AND date(clock_in) = date(?) LIMIT 1",
            (student_id, day),
        ).fetchone()
        attendance_id = attendance[0]
    conn.execute(
        "INSERT INTO logs (attendance_id, student_id, content, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (attendance_id, student_id, f"Completed demo OJT/classroom activity {index}.", day.replace(hour=17, minute=5)),
    )
    rating = min(5.0, 3.0 + index * 0.3)
    percentage = min(100.0, 80.0 + index * 3.0)
    conn.execute(
        "INSERT INTO daily_performance_ratings (attendance_id, supervisor_id, star_rating, percentage, comment) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (attendance_id, supervisor_id, rating, percentage, f"Demo performance rating {index}."),
    )

    conn.execute(
        "INSERT INTO feedback (student_id, supervisor_id, comment, performance_label, ml_prediction, ml_sentiment, ml_competency, ml_recommendation, ml_svm_prediction, ml_confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
        (student_id, supervisor_id, f"Demo feedback for student {index}.", "Good", "Good", "positive", "Technical Skills", "Continue improving practical skills.", "Good", 0.80 + index * 0.03),
    )

    conn.execute(
        "INSERT INTO notifications (user_id, title, message, notification_type, is_read, link_url) VALUES (?, ?, ?, 'info', 0, '/student/dashboard') ON CONFLICT DO NOTHING",
        (student_id, "Demo notification", f"Demo dataset {index} is ready."),
    )

    if classroom_type == "internship":
        detail = conn.execute("SELECT id FROM classroom_internship_details WHERE classroom_id = ? LIMIT 1", (classroom_id,)).fetchone()
        if not detail:
            conn.execute(
                """INSERT INTO classroom_internship_details
                (classroom_id, internship_title, company_name, industry, work_arrangement,
                 schedule_type, hours_mode, compensation, location, start_date, end_date,
                 enrollment_deadline, required_hours, company_website, company_description,
                 internship_description)
                VALUES (?, ?, ?, ?, 'Hybrid', 'fixed_dates', 'specified', 'Paid', ?, ?, ?, ?, 486, ?, ?, ?)""",
                (classroom_id, f"Software Development Internship {index}", f"Demo Company {index}", "Technology", "Quezon City, NCR", str(day.date()), str((day + timedelta(days=60)).date()), str((day - timedelta(days=2)).date()), f"https://example.com/demo{index}", f"Demo company profile {index}.", f"Demo internship opportunity {index}."),
            )
        conn.execute(
            "INSERT INTO classroom_internship_responsibilities (classroom_id, responsibility, sort_order) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (classroom_id, f"Build and test assigned features for dataset {index}.", 0),
        )
        conn.execute(
            "INSERT INTO classroom_internship_qualifications (classroom_id, qualification, sort_order) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (classroom_id, "Basic software development knowledge.", 0),
        )

    return student_id, classroom_id


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
        seeded = []
        for index in range(1, SEED_COUNT + 1):
            seeded.append(seed_one(conn, supervisor_id, index))
        conn.commit()
        print(f"Seeded {len(seeded)} complete Nexora demo datasets.")
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
