import os
import sys


ROOT_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

if ROOT_DIR not in sys.path:
    sys.path.insert(
        0,
        ROOT_DIR
    )


try:
    from dotenv import load_dotenv

    load_dotenv(
        os.path.join(
            ROOT_DIR,
            ".env"
        )
    )

except ImportError:
    pass


from app.Models.db import get_db_connection
from app.Services.email_service import send_email

if __name__ == "__main__":
    username = input(
        "Enter Nexora username: "
    ).strip()


    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                role
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            (username,)
        )

        user = cursor.fetchone()

    finally:
        cursor.close()
        conn.close()


    if not user:
        raise SystemExit(
            "User not found."
        )


    if not user["email"]:
        raise SystemExit(
            "This user has no email "
            "stored in the database."
        )


    recipient = user["email"]

    print(
        f"Sending test email to: "
        f"{recipient}"
    )


    send_email(
        recipient,
        "Nexora Email Test",
        (
            f"Hello {user['username']},\n\n"
            "Your Nexora email configuration "
            "is working correctly.\n\n"
            "Nexora"
        )
    )


    print(
        "Email sent successfully."
    )
