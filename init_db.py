from database.db import get_db_connection, using_postgres


def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    if using_postgres():
        statements = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY,
                student_id INTEGER NOT NULL REFERENCES users(id),
                clock_in TIMESTAMP NOT NULL,
                clock_out TIMESTAMP,
                hours_rendered REAL,
                status TEXT DEFAULT 'Open'
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                attendance_id INTEGER NOT NULL REFERENCES attendance(id),
                student_id INTEGER NOT NULL REFERENCES users(id),
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                student_id INTEGER NOT NULL REFERENCES users(id),
                supervisor_id INTEGER NOT NULL REFERENCES users(id),
                task_title TEXT NOT NULL,
                task_description TEXT,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deadline TIMESTAMP,
                requires_submission INTEGER DEFAULT 1,
                allow_late_submission INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Pending'
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS task_submissions (
                id SERIAL PRIMARY KEY,
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                remarks TEXT
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES users(id),
                filename TEXT,
                filepath TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES users(id),
                supervisor_id INTEGER REFERENCES users(id),
                comment TEXT,
                performance_label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS student_assignments (
                id SERIAL PRIMARY KEY,
                student_id INTEGER NOT NULL REFERENCES users(id),
                supervisor_id INTEGER NOT NULL REFERENCES users(id),
                UNIQUE(student_id, supervisor_id)
            )
            """,

            """
            ALTER TABLE feedback
            ADD COLUMN IF NOT EXISTS performance_label TEXT
            """
        ]

    else:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                clock_in TIMESTAMP NOT NULL,
                clock_out TIMESTAMP,
                hours_rendered REAL,
                status TEXT DEFAULT 'Open',
                FOREIGN KEY (student_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attendance_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (attendance_id) REFERENCES attendance(id),
                FOREIGN KEY (student_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                supervisor_id INTEGER NOT NULL,
                task_title TEXT NOT NULL,
                task_description TEXT,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deadline TIMESTAMP,
                requires_submission INTEGER DEFAULT 1,
                allow_late_submission INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Pending',
                FOREIGN KEY (student_id) REFERENCES users(id),
                FOREIGN KEY (supervisor_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS task_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                remarks TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                filename TEXT,
                filepath TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                supervisor_id INTEGER,
                comment TEXT,
                performance_label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES users(id),
                FOREIGN KEY (supervisor_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS student_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                supervisor_id INTEGER NOT NULL,
                UNIQUE(student_id, supervisor_id),
                FOREIGN KEY (student_id) REFERENCES users(id),
                FOREIGN KEY (supervisor_id) REFERENCES users(id)
            )
            """
        ]

    # Create tables
    for statement in statements:
        cursor.execute(statement)

    # SQLite compatibility for older databases
    if not using_postgres():
        columns = {
            row[1]
            for row in cursor.execute(
                "PRAGMA table_info(feedback)"
            ).fetchall()
        }

        if "performance_label" not in columns:
            cursor.execute(
                "ALTER TABLE feedback ADD COLUMN performance_label TEXT"
            )

    # ---------------------------------------------------------
    # CREATE DEFAULT ADMIN ACCOUNT
    # ---------------------------------------------------------
    cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    )

    admin_exists = cursor.fetchone()

    if not admin_exists:
        cursor.execute(
            """
            INSERT INTO users (username, password, role)
            VALUES (?, ?, ?)
            """,
            ("admin", "nexora_123", "admin")
        )

        print("Default admin account created.")

    conn.commit()
    cursor.close()
    conn.close()

    print("Database initialized successfully 🚀")


if __name__ == "__main__":
    initialize_database()