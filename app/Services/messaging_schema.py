"""Schema for authenticated one-to-one Nexora messaging."""

from app.Models.db import get_db_connection, using_postgres


def ensure_messaging_schema():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if using_postgres():
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS direct_messages (
                    id SERIAL PRIMARY KEY,
                    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    body TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_at TIMESTAMP,
                    CHECK (sender_id <> recipient_id)
                )
                """
            )
        else:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS direct_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_at TIMESTAMP,
                    CHECK (sender_id <> recipient_id),
                    FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(recipient_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_direct_messages_pair_created
            ON direct_messages(sender_id, recipient_id, created_at)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_direct_messages_recipient_read
            ON direct_messages(recipient_id, read_at, created_at)
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
