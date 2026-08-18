import sqlite3

conn = sqlite3.connect("nexora.db")

cursor = conn.cursor()

# FORCE WAL MODE (must use cursor for reliability here)
cursor.execute("PRAGMA journal_mode=WAL;")

# verify mode (optional debug)
cursor.execute("PRAGMA journal_mode;")
print("Journal mode:", cursor.fetchone())

# USERS TABLE
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL
)
""")

# ATTENDANCE TABLE
cursor.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    clock_in TIMESTAMP NOT NULL,
    clock_out TIMESTAMP,
    hours_rendered REAL,
    status TEXT DEFAULT 'Open',
    FOREIGN KEY (student_id) REFERENCES users(id)
)
""")

# LOGBOOK ENTRIES
cursor.execute("""
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attendance_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (attendance_id) REFERENCES attendance(id),
    FOREIGN KEY (student_id) REFERENCES users(id)
)
""")

# TASKS TABLE (student task records)
cursor.execute("""
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
    status TEXT DEFAULT 'Pending'
)
""")

# TASK SUBMISSIONS TABLE (student task submissions)
cursor.execute("""
CREATE TABLE IF NOT EXISTS task_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    remarks TEXT
)
""")

# DOCUMENTS TABLE (student uploads)
cursor.execute("""
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    filename TEXT,
    filepath TEXT,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# FEEDBACK TABLE
cursor.execute("""
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    supervisor_id INTEGER,
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Supervisor's Side

# STUDENT ASSIGNMENTS TABLE
cursor.execute("""
CREATE TABLE IF NOT EXISTS student_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    supervisor_id INTEGER NOT NULL
)
""")



conn.commit()
conn.close()

print("Database initialized successfully 🚀")