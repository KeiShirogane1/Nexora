from app.Models.db import get_db_connection


users = [
    ("student", "intern_123", "student"),
    ("supervisor", "superv_123", "supervisor"),
    ("admin", "nexora_123", "admin"),
]


conn = get_db_connection()
cursor = conn.cursor()

if hasattr(cursor, "executemany"):
    # PostgreSQL: ON CONFLICT keeps this idempotent.
    if "DATABASE_URL" in __import__("os").environ:
        cursor.executemany("""
            INSERT INTO users (username, password, role)
            VALUES (?, ?, ?)
            ON CONFLICT (username) DO NOTHING
        """, users)
    else:
        cursor.executemany("""
            INSERT OR IGNORE INTO users (username, password, role)
            VALUES (?, ?, ?)
        """, users)

conn.commit()
conn.close()

print("Users seeded 🚀")
