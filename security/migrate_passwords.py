from database.db import get_db_connection
from security.password_security import hash_password, is_password_hash


def migrate_passwords():
    conn = get_db_connection()
    cursor = conn.cursor()

    migrated = 0
    already_secure = 0

    try:
        cursor.execute(
            """
            SELECT id, username, password, role
            FROM users
            """
        )

        users = cursor.fetchall()

        print()
        print("Nexora Password Migration")
        print("-------------------------")
        print(f"Users found: {len(users)}")
        print()

        for user in users:
            user_id = user["id"]
            username = user["username"]
            stored_password = user["password"]
            role = user["role"]

            if is_password_hash(stored_password):
                already_secure += 1

                print(
                    f"[SECURE] {username} "
                    f"({role})"
                )

                continue

            if not stored_password:
                raise RuntimeError(
                    f"User '{username}' has an empty password."
                )

            new_password_hash = hash_password(
                stored_password
            )

            cursor.execute(
                """
                UPDATE users
                SET password = ?
                WHERE id = ?
                """,
                (
                    new_password_hash,
                    user_id
                )
            )

            migrated += 1

            print(
                f"[MIGRATED] {username} "
                f"({role})"
            )

        conn.commit()

        print()
        print("-------------------------")
        print("Migration completed.")
        print(f"Migrated: {migrated}")
        print(f"Already secure: {already_secure}")
        print(f"Total users: {len(users)}")
        print()

    except Exception:
        conn.rollback()
        print()
        print("Migration failed.")
        print("All migration changes were rolled back.")
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    migrate_passwords()