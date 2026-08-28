from database.db import get_db_connection, using_postgres


def initialize_database():

    print("Initializing Nexora database...")

    conn = get_db_connection()
    cursor = conn.cursor()

    if using_postgres():
        statements = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
<<<<<<< Updated upstream
                role TEXT NOT NULL
=======
                role TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                password_changed_at TIMESTAMP
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
        ]
=======
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS email TEXT
            """,

            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP
            """,

            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'
            """,

            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
            ON users(email)
            """,

            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                token_hash TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            """
            CREATE TABLE IF NOT EXISTS student_profiles (
                id SERIAL PRIMARY KEY,

                user_id INTEGER UNIQUE NOT NULL
                REFERENCES users(id),

                first_name TEXT,
                middle_name TEXT,
                last_name TEXT,

                age INTEGER,

                student_id TEXT UNIQUE,

                profile_picture TEXT,

                school_email TEXT,

                phone_number TEXT,

                home_address TEXT,

                grade_year TEXT,

                major_program TEXT,

                profile_completed INTEGER DEFAULT 0,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
             """
            CREATE TABLE IF NOT EXISTS internships (

                id SERIAL PRIMARY KEY,

                student_id INTEGER NOT NULL,

                company_name TEXT,

                company_address TEXT,

                supervisor_name TEXT,

                supervisor_email TEXT,

                position TEXT,

                start_date TEXT,

                end_date TEXT,

                required_hours INTEGER DEFAULT 486,

                completed_hours REAL DEFAULT 0,

                status TEXT DEFAULT 'Pending',

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(student_id)
                REFERENCES users(id)

            )
            """,
            
            """
            CREATE TABLE IF NOT EXISTS profile_history (

                id SERIAL PRIMARY KEY,

                student_id INTEGER NOT NULL
                REFERENCES users(id),

                changed_by INTEGER NOT NULL
                REFERENCES users(id),

                action TEXT NOT NULL,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """,

            """
            CREATE TABLE IF NOT EXISTS notifications (

                id SERIAL PRIMARY KEY,

                user_id INTEGER NOT NULL REFERENCES users(id),

                title TEXT NOT NULL,

                message TEXT NOT NULL,

                notification_type TEXT DEFAULT 'info',

                is_read INTEGER DEFAULT 0,

                link_url TEXT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_notifications_user_read
            ON notifications(user_id, is_read, created_at DESC)
            """,
            ]
>>>>>>> Stashed changes

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

<<<<<<< Updated upstream
=======
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """,
            
            """
            CREATE TABLE IF NOT EXISTS internships (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                student_id INTEGER NOT NULL,

                company_name TEXT,

                company_address TEXT,

                supervisor_name TEXT,

                supervisor_email TEXT,

                position TEXT,

                start_date TEXT,

                end_date TEXT,

                required_hours INTEGER DEFAULT 486,

                completed_hours REAL DEFAULT 0,

                status TEXT DEFAULT 'Pending',

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(student_id)
                REFERENCES users(id)

            )
            """,
            
            """
            CREATE TABLE IF NOT EXISTS profile_history (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                student_id INTEGER NOT NULL,

                changed_by INTEGER NOT NULL,

                action TEXT NOT NULL,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(student_id)
                REFERENCES users(id),

                FOREIGN KEY(changed_by)
                REFERENCES users(id)

            )
            """, 
            
            """
            CREATE TABLE IF NOT EXISTS notifications (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                title TEXT NOT NULL,

                message TEXT NOT NULL,

                notification_type TEXT DEFAULT 'info',

                is_read INTEGER DEFAULT 0,

                link_url TEXT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(user_id)
                REFERENCES users(id)

            )
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_notifications_user_read
            ON notifications(user_id, is_read, created_at DESC)
            """
            ]
>>>>>>> Stashed changes
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

<<<<<<< Updated upstream
    admin_exists = cursor.fetchone()
=======
        if "email" not in user_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN email TEXT"
            )

        if "password_changed_at" not in user_columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP"
            )
            
        if "status" not in user_columns:
            cursor.execute(
                """
                ALTER TABLE users
                ADD COLUMN status TEXT DEFAULT 'active'
                """
            )
            
            
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes

    if not admin_exists:
        cursor.execute(
            """
            INSERT INTO users (username, password, role)
            VALUES (?, ?, ?)
            """,
            ("admin", "nexora_123", "admin")
        )

<<<<<<< Updated upstream
<<<<<<< Updated upstream
        print("Default admin account created.")
=======
=======
>>>>>>> Stashed changes
        # Notifications compatibility (rename type -> notification_type)
        try:
            notif_cols = {
                row[1]
                for row in cursor.execute(
                    "PRAGMA table_info(notifications)"
                ).fetchall()
            }

            if "type" in notif_cols and "notification_type" not in notif_cols:
                cursor.execute(
                    "ALTER TABLE notifications ADD COLUMN notification_type TEXT DEFAULT 'info'"
                )
                cursor.execute(
                    "UPDATE notifications SET notification_type = type WHERE notification_type IS NULL"
                )

            if "notification_type" not in notif_cols and "type" not in notif_cols:
                cursor.execute(
                    "ALTER TABLE notifications ADD COLUMN notification_type TEXT DEFAULT 'info'"
                )

            if "link_url" not in notif_cols:
                cursor.execute(
                    "ALTER TABLE notifications ADD COLUMN link_url TEXT"
                )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_user_read
                ON notifications(user_id, is_read, created_at DESC)
                """
            )
        except Exception:
            pass
    else:
        # Postgres: ensure legacy 'type' column is migrated
        try:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name='notifications'
                """
            )
            pg_cols = {row[0] for row in cursor.fetchall()}
            if "type" in pg_cols and "notification_type" not in pg_cols:
                cursor.execute(
                    "ALTER TABLE notifications RENAME COLUMN type TO notification_type"
                )
            if "link_url" not in pg_cols:
                cursor.execute(
                    "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link_url TEXT"
                )
        except Exception:
            pass

  # ---------------------------------------------------------
    # TEMPORARY ADMIN RECOVERY
    # ---------------------------------------------------------

    recover_admin_from_environment(cursor)

    # ---------------------------------------------------------
    # CONFIGURE ADMIN SECURELY FROM ENVIRONMENT
    # ---------------------------------------------------------

    configure_admin_from_environment(cursor)
>>>>>>> Stashed changes

    conn.commit()
    cursor.close()
    conn.close()

    print("Database initialized successfully 🚀")

if __name__ == "__main__":
    initialize_database()