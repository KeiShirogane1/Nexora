import os

from app.Models.db import get_db_connection, using_postgres

from app.Services.password_security import (
    hash_password,
    is_password_hash,
)

def recover_admin_from_environment(cursor):
    recovery_enabled = os.environ.get(
        "ADMIN_RECOVERY_ENABLED",
        ""
    ).strip().lower()

    if recovery_enabled != "true":
        return

    admin_username = os.environ.get(
        "ADMIN_RECOVERY_USERNAME",
        ""
    ).strip()

    admin_password = os.environ.get(
        "ADMIN_RECOVERY_PASSWORD",
        ""
    )

    admin_email = os.environ.get(
        "ADMIN_RECOVERY_EMAIL",
        ""
    ).strip().lower()

    if not admin_username:
        raise RuntimeError(
            "ADMIN_RECOVERY_USERNAME is required."
        )

    if not admin_password:
        raise RuntimeError(
            "ADMIN_RECOVERY_PASSWORD is required."
        )

    if len(admin_password) < 12:
        raise RuntimeError(
            "ADMIN_RECOVERY_PASSWORD must be "
            "at least 12 characters."
        )

    # -----------------------------------------------------
    # First try to find the requested username directly.
    # -----------------------------------------------------

    cursor.execute(
        """
        SELECT id, username, role
        FROM users
        WHERE username = ?
        LIMIT 1
        """,
        (admin_username,)
    )

    admin_user = cursor.fetchone()

    if admin_user:
        if admin_user["role"] != "admin":
            raise RuntimeError(
                "ADMIN_RECOVERY_USERNAME belongs "
                "to a non-admin account."
            )

        admin_id = admin_user["id"]

    else:
        # -------------------------------------------------
        # Username did not exist.
        # Look for existing Admin accounts instead.
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT id, username, role
            FROM users
            WHERE role = ?
            ORDER BY id
            """,
            ("admin",)
        )

        existing_admins = cursor.fetchall()

        if len(existing_admins) == 1:
            admin_id = existing_admins[0]["id"]

            print(
                "Admin recovery found one existing "
                "admin account."
            )

        elif len(existing_admins) == 0:
            # ---------------------------------------------
            # No Admin exists at all.
            # Create the recovery Admin.
            # ---------------------------------------------

            cursor.execute(
                """
                INSERT INTO users (
                    username,
                    email,
                    password,
                    role,
                    password_changed_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    admin_username,
                    admin_email or None,
                    hash_password(admin_password),
                    "admin"
                )
            )

            print(
                "Admin recovery created a new "
                "admin account successfully."
            )

            return

        else:
            raise RuntimeError(
                "Multiple admin accounts exist. "
                "Automatic recovery cannot safely "
                "choose one."
            )

    # -----------------------------------------------------
    # Recover the selected Admin.
    # -----------------------------------------------------

    cursor.execute(
        """
        UPDATE users
        SET
            username = ?,
            password = ?,
            email = ?,
            password_changed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            admin_username,
            hash_password(admin_password),
            admin_email or None,
            admin_id
        )
    )

    print(
        "Admin recovery completed successfully."
    )

def configure_admin_from_environment(cursor):
    admin_username = os.environ.get(
        "ADMIN_USERNAME",
        ""
    ).strip()

    admin_password = os.environ.get(
        "ADMIN_PASSWORD",
        ""
    )

    if not admin_username and not admin_password:
        print(
            "Admin provisioning skipped: "
            "ADMIN_USERNAME and ADMIN_PASSWORD "
            "are not configured."
        )
        return

    if not admin_username or not admin_password:
        raise RuntimeError(
            "ADMIN_USERNAME and ADMIN_PASSWORD "
            "must both be configured."
        )

    if len(admin_password) < 12:
        raise RuntimeError(
            "ADMIN_PASSWORD must contain "
            "at least 12 characters."
        )

    cursor.execute(
        """
        SELECT id, username, password, role
        FROM users
        WHERE username = ?
        """,
        (admin_username,)
    )

    configured_user = cursor.fetchone()

    if configured_user:
        if configured_user["role"] != "admin":
            raise RuntimeError(
                "ADMIN_USERNAME belongs to "
                "a non-admin account."
            )

        stored_password = configured_user["password"]

        # Only upgrade an old/plaintext password.
        # Do NOT reset an already-hashed admin password
        # back to ADMIN_PASSWORD on every app restart.
        if not is_password_hash(stored_password):
            cursor.execute(
                """
                UPDATE users
                SET password = ?
                WHERE id = ?
                """,
                (
                    hash_password(admin_password),
                    configured_user["id"]
                )
            )

            print(
                "Admin password upgraded "
                "to secure password hashing."
            )

        else:
            print(
                "Admin account already uses "
                "secure password hashing."
            )

        return

    cursor.execute(
        """
        SELECT id, username
        FROM users
        WHERE role = ?
        """,
        ("admin",)
    )

    existing_admins = cursor.fetchall()

    if len(existing_admins) == 0:
        cursor.execute(
            """
            INSERT INTO users (
                username,
                password,
                role
            )
            VALUES (?, ?, ?)
            """,
            (
                admin_username,
                hash_password(admin_password),
                "admin"
            )
        )

        print(
            "Admin account created securely "
            "from environment."
        )

        return

    if len(existing_admins) == 1:
        admin_id = existing_admins[0]["id"]

        cursor.execute(
            """
            UPDATE users
            SET
                username = ?,
                password = ?
            WHERE id = ?
            """,
            (
                admin_username,
                hash_password(admin_password),
                admin_id
            )
        )

        print(
            "Existing admin credentials rotated "
            "and securely hashed."
        )
        return

    raise RuntimeError(
        "Multiple admin accounts exist. "
        "ADMIN_USERNAME must match an "
        "existing admin account."
    )

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
                email TEXT UNIQUE,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                password_changed_at TIMESTAMP
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
                ml_prediction TEXT,
                ml_sentiment TEXT,
                ml_competency TEXT,
                ml_recommendation TEXT,
                ml_svm_prediction TEXT,
                ml_confidence REAL,
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
            """,
            
            """
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
            CREATE TABLE IF NOT EXISTS change_verification_codes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                code_hash TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                attempts INTEGER DEFAULT 0,
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

                emergency_name TEXT,

                emergency_relationship TEXT,

                emergency_phone TEXT,

                emergency_email TEXT,

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

                 supervisor_id INTEGER REFERENCES users(id),

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

            """
             CREATE INDEX IF NOT EXISTS idx_student_assignments_student_id
             ON student_assignments(student_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_student_assignments_supervisor_id
             ON student_assignments(supervisor_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_tasks_student_id
             ON tasks(student_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_tasks_supervisor_id
             ON tasks(supervisor_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_internships_student_id
             ON internships(student_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_internships_supervisor_id
             ON internships(supervisor_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_feedback_student_id
             ON feedback(student_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_feedback_supervisor_id
             ON feedback(supervisor_id)
             """,

            # Classroom feature — 5 tables (Postgres)
            """
            CREATE TABLE IF NOT EXISTS classrooms (
                id SERIAL PRIMARY KEY,
                supervisor_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL,
                section TEXT NOT NULL,
                description TEXT,
                code TEXT UNIQUE NOT NULL,
                archived INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS classroom_students (
                id SERIAL PRIMARY KEY,
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(classroom_id, student_id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS classroom_posts (
                id SERIAL PRIMARY KEY,
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                author_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT,
                body TEXT NOT NULL,
                post_type TEXT DEFAULT 'announcement',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS classroom_assignments (
                id SERIAL PRIMARY KEY,
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                author_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL,
                description TEXT,
                due_at TIMESTAMP,
                points INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS classroom_submissions (
                id SERIAL PRIMARY KEY,
                assignment_id INTEGER NOT NULL REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content TEXT,
                filename TEXT,
                filepath TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'submitted',
                grade TEXT,
                feedback TEXT
            )
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classrooms_supervisor_id
            ON classrooms(supervisor_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classrooms_code
            ON classrooms(code)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_students_classroom_id
            ON classroom_students(classroom_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_students_student_id
            ON classroom_students(student_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_posts_classroom_id
            ON classroom_posts(classroom_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_assignments_classroom_id
            ON classroom_assignments(classroom_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_submissions_assignment_id
            ON classroom_submissions(assignment_id)
            """,

            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_classroom_students_unique
            ON classroom_students(classroom_id, student_id)
            """,
              ]

    else:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                password_changed_at TIMESTAMP
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
                ml_prediction TEXT,
                ml_sentiment TEXT,
                ml_competency TEXT,
                ml_recommendation TEXT,
                ml_svm_prediction TEXT,
                ml_confidence REAL,
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
            """,

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
            CREATE TABLE IF NOT EXISTS change_verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                code_hash TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """,

            """
             CREATE TABLE IF NOT EXISTS student_profiles (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
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
                 emergency_name TEXT,
                 emergency_relationship TEXT,
                 emergency_phone TEXT,
                 emergency_email TEXT,
                 profile_completed INTEGER DEFAULT 0,
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY(user_id) REFERENCES users(id)
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

                 supervisor_id INTEGER REFERENCES users(id),

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
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_student_assignments_student_id
             ON student_assignments(student_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_student_assignments_supervisor_id
             ON student_assignments(supervisor_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_tasks_student_id
             ON tasks(student_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_tasks_supervisor_id
             ON tasks(supervisor_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_internships_student_id
             ON internships(student_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_internships_supervisor_id
             ON internships(supervisor_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_feedback_student_id
             ON feedback(student_id)
             """,

            """
             CREATE INDEX IF NOT EXISTS idx_feedback_supervisor_id
             ON feedback(supervisor_id)
             """,

            # Classroom feature — 5 tables (SQLite)
            """
            CREATE TABLE IF NOT EXISTS classrooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supervisor_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL,
                section TEXT NOT NULL,
                description TEXT,
                code TEXT UNIQUE NOT NULL,
                archived INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(supervisor_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS classroom_students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(classroom_id, student_id),
                FOREIGN KEY(classroom_id) REFERENCES classrooms(id),
                FOREIGN KEY(student_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS classroom_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                author_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT,
                body TEXT NOT NULL,
                post_type TEXT DEFAULT 'announcement',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(classroom_id) REFERENCES classrooms(id),
                FOREIGN KEY(author_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS classroom_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
                author_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL,
                description TEXT,
                due_at TIMESTAMP,
                points INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(classroom_id) REFERENCES classrooms(id),
                FOREIGN KEY(author_id) REFERENCES users(id)
            )
            """,

            """
            CREATE TABLE IF NOT EXISTS classroom_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL REFERENCES classroom_assignments(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content TEXT,
                filename TEXT,
                filepath TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'submitted',
                grade TEXT,
                feedback TEXT,
                FOREIGN KEY(assignment_id) REFERENCES classroom_assignments(id),
                FOREIGN KEY(student_id) REFERENCES users(id)
            )
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classrooms_supervisor_id
            ON classrooms(supervisor_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classrooms_code
            ON classrooms(code)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_students_classroom_id
            ON classroom_students(classroom_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_students_student_id
            ON classroom_students(student_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_posts_classroom_id
            ON classroom_posts(classroom_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_assignments_classroom_id
            ON classroom_assignments(classroom_id)
            """,

            """
            CREATE INDEX IF NOT EXISTS idx_classroom_submissions_assignment_id
            ON classroom_submissions(assignment_id)
            """,

            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_classroom_students_unique
            ON classroom_students(classroom_id, student_id)
            """,
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

        # Phase 7 ML: thesis-required ML artifact columns (optional, not destructive)
        try:
            fb_cols = {
                row[1]
                for row in cursor.execute("PRAGMA table_info(feedback)").fetchall()
            }
            if "ml_prediction" not in fb_cols:
                cursor.execute("ALTER TABLE feedback ADD COLUMN ml_prediction TEXT")
            if "ml_sentiment" not in fb_cols:
                cursor.execute("ALTER TABLE feedback ADD COLUMN ml_sentiment TEXT")
            if "ml_competency" not in fb_cols:
                cursor.execute("ALTER TABLE feedback ADD COLUMN ml_competency TEXT")
            if "ml_recommendation" not in fb_cols:
                cursor.execute("ALTER TABLE feedback ADD COLUMN ml_recommendation TEXT")
            if "ml_svm_prediction" not in fb_cols:
                cursor.execute("ALTER TABLE feedback ADD COLUMN ml_svm_prediction TEXT")
            if "ml_confidence" not in fb_cols:
                cursor.execute("ALTER TABLE feedback ADD COLUMN ml_confidence REAL")
        except Exception:
            pass

        user_columns = {
            row[1]
            for row in cursor.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        }

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

        # Internships supervisor_id for Phase 3
        internship_cols = {
            row[1]
            for row in cursor.execute(
                "PRAGMA table_info(internships)"
            ).fetchall()
        }
        if "supervisor_id" not in internship_cols:
            cursor.execute(
                "ALTER TABLE internships ADD COLUMN supervisor_id INTEGER REFERENCES users(id)"
            )

        # Phase 6: student_profiles emergency columns — repeatable for SQLite
        try:
            sp_cols = {
                row[1]
                for row in cursor.execute("PRAGMA table_info(student_profiles)").fetchall()
            }
            if "emergency_name" not in sp_cols:
                cursor.execute("ALTER TABLE student_profiles ADD COLUMN emergency_name TEXT")
            if "emergency_relationship" not in sp_cols:
                cursor.execute("ALTER TABLE student_profiles ADD COLUMN emergency_relationship TEXT")
            if "emergency_phone" not in sp_cols:
                cursor.execute("ALTER TABLE student_profiles ADD COLUMN emergency_phone TEXT")
            if "emergency_email" not in sp_cols:
                cursor.execute("ALTER TABLE student_profiles ADD COLUMN emergency_email TEXT")
            if "school_email" not in sp_cols:
                cursor.execute("ALTER TABLE student_profiles ADD COLUMN school_email TEXT")
        except Exception:
            pass

        # Phase 6: useful student indexes — repeatable
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_student_status ON attendance(student_id, status, clock_in)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_attendance_id ON logs(attendance_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_student_id ON logs(student_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_submissions_task_id ON task_submissions(task_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_student_id ON documents(student_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_profile_history_student_id ON profile_history(student_id)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_open ON attendance(student_id) WHERE status='Open'")
        except Exception:
            pass

        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
            ON users(email)
            """
        )

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
            # Phase 3: internships.supervisor_id
            try:
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='internships'"
                )
                pg_intern_cols = {row[0] for row in cursor.fetchall()}
                if "supervisor_id" not in pg_intern_cols:
                    cursor.execute(
                        "ALTER TABLE internships ADD COLUMN supervisor_id INTEGER REFERENCES users(id)"
                    )
            except Exception:
                pass
            # Phase 6: student_profiles emergency columns — repeatable for Postgres
            try:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='student_profiles'")
                pg_sp_cols = {row[0] for row in cursor.fetchall()}
                if "emergency_name" not in pg_sp_cols:
                    cursor.execute("ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS emergency_name TEXT")
                if "emergency_relationship" not in pg_sp_cols:
                    cursor.execute("ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS emergency_relationship TEXT")
                if "emergency_phone" not in pg_sp_cols:
                    cursor.execute("ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS emergency_phone TEXT")
                if "emergency_email" not in pg_sp_cols:
                    cursor.execute("ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS emergency_email TEXT")
                if "school_email" not in pg_sp_cols:
                    cursor.execute("ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS school_email TEXT")
            except Exception:
                pass
            # Phase 6: useful student indexes — repeatable
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_student_status ON attendance(student_id, status, clock_in)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_attendance_id ON logs(attendance_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_student_id ON logs(student_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_submissions_task_id ON task_submissions(task_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_student_id ON documents(student_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_profile_history_student_id ON profile_history(student_id)")
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_open ON attendance(student_id) WHERE status='Open'")
            except Exception:
                pass
            # Phase 7 ML columns for Postgres
            try:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='feedback'")
                pg_fb_cols = {row[0] for row in cursor.fetchall()}
                if "ml_prediction" not in pg_fb_cols:
                    cursor.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ml_prediction TEXT")
                if "ml_sentiment" not in pg_fb_cols:
                    cursor.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ml_sentiment TEXT")
                if "ml_competency" not in pg_fb_cols:
                    cursor.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ml_competency TEXT")
                if "ml_recommendation" not in pg_fb_cols:
                    cursor.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ml_recommendation TEXT")
                if "ml_svm_prediction" not in pg_fb_cols:
                    cursor.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ml_svm_prediction TEXT")
                if "ml_confidence" not in pg_fb_cols:
                    cursor.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ml_confidence REAL")
            except Exception:
                pass
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

    conn.commit()
    cursor.close()
    conn.close()

    print("Database initialized successfully")

if __name__ == "__main__":
    initialize_database()