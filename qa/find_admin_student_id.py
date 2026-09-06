import sqlite3

conn = sqlite3.connect('nexora.db')
conn.row_factory = sqlite3.Row

student = conn.execute("SELECT id FROM users WHERE role='student' LIMIT 1").fetchone()
supervisor = conn.execute("SELECT id FROM users WHERE role='supervisor' LIMIT 1").fetchone()
classroom = conn.execute("SELECT id, supervisor_id FROM classrooms LIMIT 1").fetchone()
assignment = conn.execute("SELECT id, classroom_id FROM classroom_assignments LIMIT 1").fetchone()

print(f"Valid Student ID: {student['id'] if student else None}")
print(f"Valid Supervisor ID: {supervisor['id'] if supervisor else None}")
print(f"Valid Classroom ID: {classroom['id'] if classroom else None}")
print(f"Valid Assignment ID: {assignment['id'] if assignment else None}")

conn.close()
