import uuid

from app.Services.classwork_ml_service import build_student_performance_features


def test_ml_features_aggregate_normalized_scores(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup_{uid}", f"mlsup_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    student = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlstu_{uid}", f"mlstu_{uid}@example.com", "x", "student"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML Class", "A", supervisor, f"NXR-ML{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "Quiz", 10)).fetchone()[0]
    a2 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "Project", 20)).fetchone()[0]
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1,student,8,10,80,"manual"))
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a2,student,15,20,75,"imported"))
    db.commit()

    features = build_student_performance_features(student, classroom)
    assert features["graded_count"] == 2
    assert features["total_count"] == 2
    assert features["average_percentage"] == 77.5
    assert features["min_percentage"] == 75.0
    assert features["max_percentage"] == 80.0
    assert features["completion_rate"] == 100.0
    assert features["manual_count"] == 1
    assert features["imported_count"] == 1


def test_ml_features_are_empty_when_no_scores(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup2_{uid}", f"mlsup2_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML Empty", "A", supervisor, f"NXR-ME{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.commit()

    features = build_student_performance_features(999999, classroom)
    assert features["graded_count"] == 0
    assert features["average_percentage"] is None
    assert features["completion_rate"] == 0.0
