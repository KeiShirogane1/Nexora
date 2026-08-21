from getpass import getpass

from database.db import get_db_connection
from security.password_security import hash_password


VALID_ROLES = {
    "student",
    "supervisor",
    "admin",
}


def create_user():
    print("Nexora User Seeder")
    print("------------------")

    username = input("Username: ").strip()

    if not username:
        raise ValueError("Username cannot be empty.")

    role = input(
        "Role (student/supervisor/admin): "
    ).strip().lower()

    if role not in VALID_ROLES:
        raise ValueError(
            "Role must be student, supervisor, or admin."
        )

    password = getpass("Password: ")
    confirm_password = getpass("Confirm password: ")

    if password != confirm_password:
        raise ValueError("Passwords do not match.")

    if len(password) < 12:
        raise ValueError(
            "Password must contain at least 12 characters."
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Check whether username already exists.
        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE username = ?
            """,
            (username,)
        )

        if cursor.fetchone():
            raise ValueError(
                "A user with that username already exists."
            )

        # Hash before storing.
        password_hash = hash_password(password)

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
                username,
                password_hash,
                role
            )
        )

        conn.commit()

        print(
            f"User '{username}' created successfully "
            f"with role '{role}'."
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    create_user()