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
                    max_group_size INTEGER DEFAULT 1
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
                    FOREIGN KEY(assignment_id) REFERENCES classroom_assignments(id) ON DELETE CASCADE
                )""",
            ]
        for statement in statements:
            conn.execute(statement)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_classrooms_supervisor ON classrooms(supervisor_id)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_students_class ON classroom_students(classroom_id)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_students_student ON classroom_students(student_id)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_posts_class ON classroom_posts(classroom_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_assignments_class ON classroom_assignments(classroom_id, due_at)",
            "CREATE INDEX IF NOT EXISTS idx_classroom_submissions_assignment ON classroom_submissions(assignment_id)",
        ]
        for statement in indexes:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()
