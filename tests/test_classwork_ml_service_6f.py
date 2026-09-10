import uuid
from unittest.mock import patch

from app.Services.classwork_ml_service import (
    build_student_performance_features,
    build_student_ml_analysis,
    classify_numeric_performance,
)


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


def test_total_count_represents_all_assignments_not_only_graded(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup3_{uid}", f"mlsup3_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    student = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlstu3_{uid}", f"mlstu3_{uid}@example.com", "x", "student"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML Total", "A", supervisor, f"NXR-MT{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    # create 3 assignments but only grade 1 for student
    a1 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A1", 100)).fetchone()[0]
    a2 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A2", 100)).fetchone()[0]
    a3 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A3", 100)).fetchone()[0]
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 90, 100, 90, "manual"))
    db.commit()

    features = build_student_performance_features(student, classroom)
    assert features["total_count"] == 3, "total_count must count ALL classroom assignments"
    assert features["graded_count"] == 1
    # also verify total_count != graded_count when some assignments ungraded
    assert features["total_count"] != features["graded_count"]


def test_completion_rate_is_graded_over_total_times_100(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup4_{uid}", f"mlsup4_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    student = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlstu4_{uid}", f"mlstu4_{uid}@example.com", "x", "student"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML Completion", "A", supervisor, f"NXR-MC{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A1", 100)).fetchone()[0]
    a2 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A2", 100)).fetchone()[0]
    a3 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A3", 100)).fetchone()[0]
    a4 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A4", 100)).fetchone()[0]
    # grade 1 of 4
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 80, 100, 80, "manual"))
    db.commit()
    features = build_student_performance_features(student, classroom)
    assert features["total_count"] == 4
    assert features["graded_count"] == 1
    assert features["completion_rate"] == 25.0  # 1/4 *100

    # add second grade, expect 50%
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a2, student, 70, 100, 70, "imported"))
    db.commit()
    features2 = build_student_performance_features(student, classroom)
    assert features2["graded_count"] == 2
    assert features2["total_count"] == 4
    assert features2["completion_rate"] == 50.0  # 2/4*100

    # test full completion
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a3, student, 60, 100, 60, "manual"))
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a4, student, 90, 100, 90, "manual"))
    db.commit()
    features3 = build_student_performance_features(student, classroom)
    assert features3["completion_rate"] == 100.0


def test_completion_rate_zero_when_no_assignments_or_no_graded(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup5_{uid}", f"mlsup5_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    student = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlstu5_{uid}", f"mlstu5_{uid}@example.com", "x", "student"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML Zero", "A", supervisor, f"NXR-MZ{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    # classroom has 2 assignments but no scores
    db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A1", 10))
    db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A2", 10))
    db.commit()
    features = build_student_performance_features(student, classroom)
    assert features["graded_count"] == 0
    assert features["total_count"] == 2
    assert features["completion_rate"] == 0.0


def test_numeric_performance_labels_thresholds():
    # >=90 Excellent
    assert classify_numeric_performance(90) == "Excellent"
    assert classify_numeric_performance(95) == "Excellent"
    assert classify_numeric_performance(100) == "Excellent"
    # 89.9 should be Very Satisfactory
    assert classify_numeric_performance(89.9) == "Very Satisfactory"
    # >=85 Very Satisfactory
    assert classify_numeric_performance(85) == "Very Satisfactory"
    assert classify_numeric_performance(87) == "Very Satisfactory"
    # 84.9 should be Satisfactory
    assert classify_numeric_performance(84.9) == "Satisfactory"
    # >=75 Satisfactory
    assert classify_numeric_performance(75) == "Satisfactory"
    assert classify_numeric_performance(80) == "Satisfactory"
    # 74.9 should be Fair
    assert classify_numeric_performance(74.9) == "Fair"
    # >=60 Fair
    assert classify_numeric_performance(60) == "Fair"
    assert classify_numeric_performance(65) == "Fair"
    # <60 Needs Improvement
    assert classify_numeric_performance(59.9) == "Needs Improvement"
    assert classify_numeric_performance(0) == "Needs Improvement"
    assert classify_numeric_performance(30) == "Needs Improvement"
    # None should map to Satisfactory per implementation
    assert classify_numeric_performance(None) == "Satisfactory"


def test_numeric_performance_labels_via_features_integration(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup6_{uid}", f"mlsup6_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    student = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlstu6_{uid}", f"mlstu6_{uid}@example.com", "x", "student"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML Label", "A", supervisor, f"NXR-ML{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A1", 100)).fetchone()[0]
    # 92% -> Excellent
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 92, 100, 92, "manual"))
    db.commit()
    features = build_student_performance_features(student, classroom)
    assert classify_numeric_performance(features["average_percentage"]) == "Excellent"
    # update to 85 -> Very Satisfactory
    db.execute("UPDATE classwork_scores SET percentage=85, score=85 WHERE assignment_id=? AND student_id=?", (a1, student))
    db.commit()
    features2 = build_student_performance_features(student, classroom)
    assert classify_numeric_performance(features2["average_percentage"]) == "Very Satisfactory"


def test_build_student_ml_analysis_empty_feedback(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup7_{uid}", f"mlsup7_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    student = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlstu7_{uid}", f"mlstu7_{uid}@example.com", "x", "student"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML EmptyFB", "A", supervisor, f"NXR-ME{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A1", 100)).fetchone()[0]
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 80, 100, 80, "manual"))
    db.commit()

    # empty string
    result = build_student_ml_analysis(student, classroom, feedback_text="")
    assert "features" in result
    assert "numeric_performance_label" in result
    assert "feedback_analysis" in result
    assert result["feedback_analysis"]["is_empty"] is True
    assert result["numeric_performance_label"] == "Satisfactory"  # 80% -> Satisfactory
    assert result["performance_label"] == result["numeric_performance_label"]
    # sentiment etc should exist without breaking
    assert "sentiment" in result
    assert "competency" in result
    assert "recommendation" in result

    # whitespace only should also be empty
    result2 = build_student_ml_analysis(student, classroom, feedback_text="   ")
    assert result2["feedback_analysis"]["is_empty"] is True

    # None handling (if passed as None, should not raise)
    result3 = build_student_ml_analysis(student, classroom, feedback_text=None)
    assert result3["feedback_analysis"]["is_empty"] is True


def test_build_student_ml_analysis_with_feedback_calls_predictor(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup8_{uid}", f"mlsup8_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    student = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlstu8_{uid}", f"mlstu8_{uid}@example.com", "x", "student"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML WithFB", "A", supervisor, f"NXR-MW{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A1", 100)).fetchone()[0]
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 88, 100, 88, "manual"))
    db.commit()

    feedback = "Outstanding work, excellent performance and great leadership"

    with patch("app.Services.classwork_ml_service.analyze_feedback_detailed") as mock_predict:
        mock_predict.return_value = {
            "performance_label": "Excellent",
            "nb_prediction": "Excellent",
            "svm_prediction": "Excellent",
            "sentiment": "Positive",
            "competency": "Outstanding Competency",
            "recommendation": "Continue excellent performance; consider leadership opportunities and advanced responsibilities.",
            "confidence": 0.95,
            "is_empty": False,
        }
        result = build_student_ml_analysis(student, classroom, feedback_text=feedback)
        # verify predictor was called exactly once with feedback text without breaking
        mock_predict.assert_called_once()
        called_arg = mock_predict.call_args[0][0]
        assert called_arg == feedback
        # verify result merges correctly
        assert result["feedback_analysis"]["performance_label"] == "Excellent"
        assert result["sentiment"] == "Positive"
        assert result["competency"] == "Outstanding Competency"
        assert result["confidence"] == 0.95
        # numeric label from features should still be present (88% -> Very Satisfactory)
        assert result["numeric_performance_label"] == "Very Satisfactory"
        assert result["features"]["average_percentage"] == 88


def test_build_student_ml_analysis_with_real_feedback_no_break(client, db):
    uid = uuid.uuid4().hex[:8]
    supervisor = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlsup9_{uid}", f"mlsup9_{uid}@example.com", "x", "supervisor"),
    ).fetchone()[0]
    student = db.execute(
        "INSERT INTO users (username,email,password,role) VALUES (?,?,?,?) RETURNING id",
        (f"mlstu9_{uid}", f"mlstu9_{uid}@example.com", "x", "student"),
    ).fetchone()[0]
    classroom = db.execute(
        "INSERT INTO classrooms (name,section,supervisor_id,code,archived) VALUES (?,?,?,?,?) RETURNING id",
        ("ML RealFB", "A", supervisor, f"NXR-MR{uid[:6].upper()}", 0),
    ).fetchone()[0]
    db.execute("INSERT INTO classroom_students (classroom_id,student_id) VALUES (?,?)", (classroom, student))
    a1 = db.execute("INSERT INTO classroom_assignments (classroom_id,author_id,title,points) VALUES (?,?,?,?) RETURNING id", (classroom, supervisor, "A1", 100)).fetchone()[0]
    db.execute("INSERT INTO classwork_scores (assignment_id,student_id,score,max_score,percentage,grading_method) VALUES (?,?,?,?,?,?)", (a1, student, 75, 100, 75, "imported"))
    db.commit()

    # Real predictor call with non-empty feedback
    result = build_student_ml_analysis(student, classroom, feedback_text="Good job, meets expectations and consistent follow-through")
    assert result["feedback_analysis"]["is_empty"] is False
    assert result["feedback_analysis"]["performance_label"] in {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}
    assert result["sentiment"] in {"Positive", "Neutral", "Negative"}
    assert "competency" in result and result["competency"]
    assert "recommendation" in result and result["recommendation"]
    assert isinstance(result["confidence"], float)
    # numeric label should be Satisfactory (75%)
    assert result["numeric_performance_label"] == "Satisfactory"
    assert result["performance_label"] == result["numeric_performance_label"]
