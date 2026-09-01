"""Schema for normalized Classwork performance records."""

from app.Models.db import get_db_connection, using_postgres


def ensure_classwork_score_schema():
    conn = get_db_connection()
    try:
        if using_postgres():
            statement = """CREATE TABLE IF NOT EXISTS classwork_scores (
                id SERIAL PRIMARY KEY,
                assignment_id INTEGER NOT NULL REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                score NUMERIC NOT NULL,
                max_score NUMERIC NOT NULL,
                percentage NUMERIC NOT NULL,
                grading_method TEXT NOT NULL DEFAULT 'imported',
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(assignment_id, student_id)
            )"""
        else:
            statement = """CREATE TABLE IF NOT EXISTS classwork_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                score NUMERIC NOT NULL,
                max_score NUMERIC NOT NULL,
                percentage NUMERIC NOT NULL,
                grading_method TEXT NOT NULL DEFAULT 'imported',
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(assignment_id, student_id),
                FOREIGN KEY(assignment_id) REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
            )"""
        conn.execute(statement)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_classwork_scores_student ON classwork_scores(student_id, assignment_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_classwork_scores_assignment ON classwork_scores(assignment_id, student_id)")
        conn.commit()
    finally:
        conn.close()
