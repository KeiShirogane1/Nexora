"""Phase 11 classroom schema and helpers.

The classroom feature is intentionally additive: existing tasks, logbook,
attendance, feedback, and assignment workflows remain unchanged.
"""
from app.Models.db import get_db_connection, using_postgres


def ensure_classroom_schema():
    conn = get_db_connection()
    try:
        if using_postgres():
            statements = [
                """CREATE TABLE IF NOT EXISTS classrooms (
                    id SERIAL PRIMARY KEY,
                    supervisor_id INTEGER NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL,
                    section TEXT NOT NULL,
                    description TEXT,
                    code TEXT UNIQUE NOT NULL,
                    classroom_type TEXT NOT NULL DEFAULT 'classroom',
                    banner_theme TEXT NOT NULL DEFAULT 'blue',
                    archived INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_students (
                    id SERIAL PRIMARY KEY,
                    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(classroom_id, student_id)
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_posts (
                    id SERIAL PRIMARY KEY,
                    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                    author_id INTEGER NOT NULL REFERENCES users(id),
                    title TEXT,
                    body TEXT NOT NULL,
                    post_type TEXT DEFAULT 'announcement',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_assignments (
                    id SERIAL PRIMARY KEY,
                    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                    author_id INTEGER NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL,
                    description TEXT,
                    due_at TIMESTAMP,
                    points INTEGER DEFAULT 100,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_submissions (
                    id SERIAL PRIMARY KEY,
                    assignment_id INTEGER NOT NULL REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    content TEXT,
                    filename TEXT,
                    filepath TEXT,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'submitted',
                    grade TEXT,
                    feedback TEXT,
                    UNIQUE(assignment_id, student_id)
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_assignment_meta (
                    assignment_id INTEGER PRIMARY KEY REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                    activity_type TEXT NOT NULL DEFAULT 'assignment',
                    external_url TEXT,
                    resource_label TEXT,
                    resource_filename TEXT,
                    resource_filepath TEXT,
                    allow_file_upload INTEGER DEFAULT 0,
                    group_mode INTEGER DEFAULT 0,
                    max_group_size INTEGER DEFAULT 1,
                    team_name TEXT,
                    submission_mode TEXT NOT NULL DEFAULT 'individual'
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_assignment_recipients (
                    id SERIAL PRIMARY KEY,
                    assignment_id INTEGER NOT NULL REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(assignment_id, student_id)
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_internship_details (
                    id SERIAL PRIMARY KEY,
                    classroom_id INTEGER UNIQUE NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                    internship_title TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT,
                    work_arrangement TEXT NOT NULL DEFAULT 'On-site',
                    schedule_type TEXT NOT NULL DEFAULT 'fixed_dates',
                    hours_mode TEXT NOT NULL DEFAULT 'specified',
                    compensation TEXT NOT NULL DEFAULT 'Not Specified',
                    location TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    enrollment_deadline TEXT,
                    required_hours INTEGER NOT NULL DEFAULT 0,
                    company_website TEXT,
                    company_description TEXT,
                    internship_description TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_internship_responsibilities (
                    id SERIAL PRIMARY KEY,
                    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                    responsibility TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_internship_qualifications (
                    id SERIAL PRIMARY KEY,
                    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                    qualification TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0
                )""",
            ]
        else:
            statements = [
                """CREATE TABLE IF NOT EXISTS classrooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supervisor_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    section TEXT NOT NULL,
                    description TEXT,
                    code TEXT UNIQUE NOT NULL,
                    classroom_type TEXT NOT NULL DEFAULT 'classroom',
                    banner_theme TEXT NOT NULL DEFAULT 'blue',
                    archived INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(supervisor_id) REFERENCES users(id)
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    classroom_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(classroom_id, student_id),
                    FOREIGN KEY(classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE,
                    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    classroom_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    title TEXT,
                    body TEXT NOT NULL,
                    post_type TEXT DEFAULT 'announcement',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE,
                    FOREIGN KEY(author_id) REFERENCES users(id)
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    classroom_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    due_at TIMESTAMP,
                    points INTEGER DEFAULT 100,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE,
                    FOREIGN KEY(author_id) REFERENCES users(id)
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    content TEXT,
                    filename TEXT,
                    filepath TEXT,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'submitted',
                    grade TEXT,
                    feedback TEXT,
                    UNIQUE(assignment_id, student_id),
                    FOREIGN KEY(assignment_id) REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_assignment_meta (
                    assignment_id INTEGER PRIMARY KEY,
                    activity_type TEXT NOT NULL DEFAULT 'assignment',
                    external_url TEXT,
                    resource_label TEXT,
                    resource_filename TEXT,
                    resource_filepath TEXT,
                    allow_file_upload INTEGER DEFAULT 0,
                    group_mode INTEGER DEFAULT 0,
                    max_group_size INTEGER DEFAULT 1,
                    team_name TEXT,
                    submission_mode TEXT NOT NULL DEFAULT 'individual',
                    FOREIGN KEY(assignment_id) REFERENCES classroom_assignments(id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_assignment_recipients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(assignment_id, student_id),
                    FOREIGN KEY(assignment_id) REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_internship_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    classroom_id INTEGER UNIQUE NOT NULL,
                    internship_title TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    industry TEXT,
                    work_arrangement TEXT NOT NULL DEFAULT 'On-site',
                    schedule_type TEXT NOT NULL DEFAULT 'fixed_dates',
                    hours_mode TEXT NOT NULL DEFAULT 'specified',
                    compensation TEXT NOT NULL DEFAULT 'Not Specified',
                    location TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    enrollment_deadline TEXT,
                    required_hours INTEGER NOT NULL DEFAULT 0,
                    company_website TEXT,
                    company_description TEXT,
                    internship_description TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_internship_responsibilities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    classroom_id INTEGER NOT NULL,
                    responsibility TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS classroom_internship_qualifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    classroom_id INTEGER NOT NULL,
                    qualification TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE
                )""",
            ]
        for statement in statements:
            conn.execute(statement)

        # Existing installations created before Internship Classroom support need
        # additive columns added without rebuilding their tables.
        if using_postgres():
            conn.execute(
                "ALTER TABLE classrooms ADD COLUMN IF NOT EXISTS classroom_type TEXT NOT NULL DEFAULT 'classroom'"
            )
            conn.execute(
                "ALTER TABLE classrooms ADD COLUMN IF NOT EXISTS banner_theme TEXT NOT NULL DEFAULT 'blue'"
            )
            conn.execute(
                "ALTER TABLE classroom_internship_details ADD COLUMN IF NOT EXISTS schedule_type TEXT NOT NULL DEFAULT 'fixed_dates'"
            )
            conn.execute(
                "ALTER TABLE classroom_internship_details ADD COLUMN IF NOT EXISTS hours_mode TEXT NOT NULL DEFAULT 'specified'"
            )
            conn.execute(
                "ALTER TABLE classroom_assignment_meta ADD COLUMN IF NOT EXISTS team_name TEXT"
            )
            conn.execute(
                "ALTER TABLE classroom_assignment_meta ADD COLUMN IF NOT EXISTS submission_mode TEXT NOT NULL DEFAULT 'individual'"
            )
        else:
            classroom_columns = [row[1] for row in conn.execute("PRAGMA table_info(classrooms)").fetchall()]
            if "classroom_type" not in classroom_columns:
                conn.execute(
                    "ALTER TABLE classrooms ADD COLUMN classroom_type TEXT NOT NULL DEFAULT 'classroom'"
                )
            if "banner_theme" not in classroom_columns:
                conn.execute(
                    "ALTER TABLE classrooms ADD COLUMN banner_theme TEXT NOT NULL DEFAULT 'blue'"
                )
            internship_columns = [
                row[1] for row in conn.execute("PRAGMA table_info(classroom_internship_details)").fetchall()
            ]
            if "schedule_type" not in internship_columns:
                conn.execute(
                    "ALTER TABLE classroom_internship_details ADD COLUMN schedule_type TEXT NOT NULL DEFAULT 'fixed_dates'"
                )
            if "hours_mode" not in internship_columns:
                conn.execute(
                    "ALTER TABLE classroom_internship_details ADD COLUMN hours_mode TEXT NOT NULL DEFAULT 'specified'"
                )
            assignment_meta_columns = [
                row[1] for row in conn.execute("PRAGMA table_info(classroom_assignment_meta)").fetchall()
            ]
            if "team_name" not in assignment_meta_columns:
                conn.execute(
                    "ALTER TABLE classroom_assignment_meta ADD COLUMN team_name TEXT"
                )
            if "submission_mode" not in assignment_meta_columns:
                conn.execute(
                    "ALTER TABLE classroom_assignment_meta ADD COLUMN submission_mode TEXT NOT NULL DEFAULT 'individual'"
                )

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_classrooms_supervisor ON classrooms(supervisor_id)",
            "CREATE INDEX IF NOT EXISTS idx_classrooms_type ON classrooms(classroom_type)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_students_class ON classroom_students(classroom_id)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_students_student ON classroom_students(student_id)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_posts_class ON classroom_posts(classroom_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_assignments_class ON classroom_assignments(classroom_id, due_at)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_assignment_recipients_assignment ON classroom_assignment_recipients(assignment_id)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_assignment_recipients_student ON classroom_assignment_recipients(student_id)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_submissions_assignment ON classroom_submissions(assignment_id)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_internship_responsibilities_class ON classroom_internship_responsibilities(classroom_id, sort_order)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_internship_qualifications_class ON classroom_internship_qualifications(classroom_id, sort_order)",
        ]
        for statement in indexes:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()
