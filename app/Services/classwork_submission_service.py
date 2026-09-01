"""Database schema for the Phase 3 classwork submission workflow."""
from app.Models.db import get_db_connection, using_postgres


def ensure_classwork_submission_schema():
    conn = get_db_connection()
    try:
        if using_postgres():
            statements = [
                """CREATE TABLE IF NOT EXISTS classwork_submissions (
                    id SERIAL PRIMARY KEY,
                    assignment_id INTEGER NOT NULL REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    attempt_no INTEGER NOT NULL DEFAULT 1,
                    content TEXT,
                    status TEXT NOT NULL DEFAULT 'submitted',
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    grade NUMERIC,
                    feedback TEXT,
                    UNIQUE(assignment_id, student_id, attempt_no)
                )""",
                """CREATE TABLE IF NOT EXISTS classwork_submission_files (
                    id SERIAL PRIMARY KEY,
                    submission_id INTEGER NOT NULL REFERENCES classwork_submissions(id) ON DELETE CASCADE,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""",
            ]
        else:
            statements = [
                """CREATE TABLE IF NOT EXISTS classwork_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    attempt_no INTEGER NOT NULL DEFAULT 1,
                    content TEXT,
                    status TEXT NOT NULL DEFAULT 'submitted',
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    grade NUMERIC,
                    feedback TEXT,
                    UNIQUE(assignment_id, student_id, attempt_no),
                    FOREIGN KEY(assignment_id) REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                    FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
                )""",
                """CREATE TABLE IF NOT EXISTS classwork_submission_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submission_id INTEGER NOT NULL,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(submission_id) REFERENCES classwork_submissions(id) ON DELETE CASCADE
                )""",
            ]
        for statement in statements:
            conn.execute(statement)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_classwork_submissions_assignment ON classwork_submissions(assignment_id, student_id, attempt_no)",
            "CREATE INDEX IF NOT EXISTS idx_classwork_submission_files_submission ON classwork_submission_files(submission_id)",
        ]
        for statement in indexes:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()
