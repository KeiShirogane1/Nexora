import os

from database.db import get_db_connection, using_postgres

from security.password_security import (
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
            """
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

        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
            ON users(email)
            """
        )

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

    print("Database initialized successfully 🚀")


if __name__ == "__main__":
    initialize_database()