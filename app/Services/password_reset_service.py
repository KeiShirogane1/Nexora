import hashlib
import secrets

from datetime import datetime, timedelta, timezone

from app.Models.db import get_db_connection


RESET_TOKEN_MINUTES = 30


def hash_reset_token(token):
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def create_reset_token(user_id):
    token = secrets.token_urlsafe(48)

    token_hash = hash_reset_token(token)

    expires_at = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(
            minutes=RESET_TOKEN_MINUTES
        )
    )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Invalidate previous unused reset links.
        cursor.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
              AND used_at IS NULL
            """,
            (user_id,)
        )

        cursor.execute(
            """
            INSERT INTO password_reset_tokens (
                user_id,
                token_hash,
                expires_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                token_hash,
                expires_at
            )
        )

        conn.commit()

        return token

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def get_valid_reset_token(token):
    token_hash = hash_reset_token(token)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                prt.id,
                prt.user_id,
                u.username,
                u.email
            FROM password_reset_tokens prt
            JOIN users u
                ON u.id = prt.user_id
            WHERE prt.token_hash = ?
              AND prt.used_at IS NULL
              AND prt.expires_at > CURRENT_TIMESTAMP
            LIMIT 1
            """,
            (token_hash,)
        )

        return cursor.fetchone()

    finally:
        cursor.close()
        conn.close()


def mark_reset_token_used(token):
    token_hash = hash_reset_token(token)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = CURRENT_TIMESTAMP
            WHERE token_hash = ?
              AND used_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
            """,
            (token_hash,)
        )

        was_used = cursor.rowcount == 1

        conn.commit()

        return was_used

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def invalidate_user_reset_tokens(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
              AND used_at IS NULL
            """,
            (user_id,)
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()