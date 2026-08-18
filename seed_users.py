import sqlite3

conn = sqlite3.connect("nexora.db")
cursor = conn.cursor()

users = [
    ("student", "intern_123", "student"),
    ("supervisor", "superv_123", "supervisor"),
    ("admin", "nexora_123", "admin")
]

cursor.executemany("""
INSERT OR IGNORE INTO users (username, password, role)
VALUES (?, ?, ?)
""", users)

conn.commit()
conn.close()

print("Users seeded 🚀")