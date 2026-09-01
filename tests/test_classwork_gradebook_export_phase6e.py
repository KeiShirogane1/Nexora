import csv
from io import StringIO


def _login(client, user_id, role="supervisor"):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["role"] = role


def test_supervisor_gradebook_export_requires_owner(client, db):
    supervisor = db.execute("INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?) RETURNING id", ("supervisor-export", "sup-export@example.com", "x", "supervisor")).fetchone()[0]
    other = db.execute("INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?) RETURNING id", ("other-export", "other-export@example.com", "x", "supervisor")).fetchone()[0]
    class_id = db.execute("INSERT INTO classrooms (name, section, supervisor_id, archived) VALUES (?, ?, ?, ?) RETURNING id", ("Export Class", "A", supervisor, 0)).fetchone()[0]
    db.commit()

    _login(client, other)
    response = client.get(f"/supervisor/classes/{class_id}/gradebook/export.csv")
    assert response.status_code == 404


def test_supervisor_gradebook_export_csv_contains_scores_and_overall(client, db):
    supervisor = db.execute("INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?) RETURNING id", ("supervisor-csv", "sup-csv@example.com", "x", "supervisor")).fetchone()[0]
    student = db.execute("INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?) RETURNING id", ("alice", "alice@example.com", "x", "student")).fetchone()[0]
    class_id = db.execute("INSERT INTO classrooms (name, section, supervisor_id, archived) VALUES (?, ?, ?, ?) RETURNING id", ("CSV Class", "A", supervisor, 0)).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)", (class_id, student))
    a1 = db.execute("INSERT INTO classroom_assignments (classroom_id, title, points) VALUES (?, ?, ?) RETURNING id", (class_id, "Quiz 1", 20)).fetchone()[0]
    a2 = db.execute("INSERT INTO classroom_assignments (classroom_id, title, points) VALUES (?, ?, ?) RETURNING id", (class_id, "Project", 50)).fetchone()[0]
    db.execute("INSERT INTO classwork_scores (assignment_id, student_id, score, max_score, percentage, grading_method) VALUES (?, ?, ?, ?, ?, ?)", (a1, student, 18, 20, 90, "manual"))
    db.commit()

    _login(client, supervisor)
    response = client.get(f"/supervisor/classes/{class_id}/gradebook/export.csv")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in response.headers["Content-Disposition"]

    text = response.get_data(as_text=True).lstrip("\ufeff")
    rows = list(csv.reader(StringIO(text)))
    assert rows[0] == ["Student Number", "Student", "Email", "Quiz 1", "Project", "Overall %"]
    assert rows[1][1:3] == ["alice", "alice@example.com"]
    assert rows[1][3:] == ["18", "", "90.0"]
