import sqlite3


conn = sqlite3.connect("nexora.db")

cursor = conn.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS student_profiles (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_id INTEGER UNIQUE NOT NULL,

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

    profile_completed INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
    REFERENCES users(id)

)
""")


conn.commit()

conn.close()


print("student_profiles table created successfully.")