from app.Models.db import get_db_connection, using_postgres


def ensure_supervisor_profile_schema():
    conn = get_db_connection()
    try:
        if using_postgres():
            conn.execute("""
                CREATE TABLE IF NOT EXISTS supervisor_profiles (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    first_name TEXT,
                    middle_name TEXT,
                    last_name TEXT,
                    employee_id TEXT UNIQUE,
                    job_title TEXT,
                    department TEXT,
                    specialization TEXT,
                    years_experience INTEGER DEFAULT 0,
                    education TEXT,
                    certifications TEXT,
                    phone_number TEXT,
                    office_location TEXT,
                    office_hours TEXT,
                    preferred_contact TEXT,
                    response_time TEXT,
                    availability TEXT,
                    skills TEXT,
                    bio TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS supervisor_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    first_name TEXT,
                    middle_name TEXT,
                    last_name TEXT,
                    employee_id TEXT UNIQUE,
                    job_title TEXT,
                    department TEXT,
                    specialization TEXT,
                    years_experience INTEGER DEFAULT 0,
                    education TEXT,
                    certifications TEXT,
                    phone_number TEXT,
                    office_location TEXT,
                    office_hours TEXT,
                    preferred_contact TEXT,
                    response_time TEXT,
                    availability TEXT,
                    skills TEXT,
                    bio TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
        conn.commit()
    finally:
        conn.close()


def get_or_create_supervisor_profile(user_id):
    ensure_supervisor_profile_schema()
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM supervisor_profiles WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return row
        conn.execute("INSERT INTO supervisor_profiles (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return conn.execute("SELECT * FROM supervisor_profiles WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
