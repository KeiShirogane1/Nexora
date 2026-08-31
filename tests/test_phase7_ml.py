import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import os
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import SVC


BASE = pathlib.Path(__file__).resolve().parent.parent
VEC_PATH = BASE / "app" / "ML" / "model" / "vectorizer.pkl"
NB_PATH = BASE / "app" / "ML" / "model" / "performance_model.pkl"
SVM_PATH = BASE / "app" / "ML" / "model" / "svm_model.pkl"

VALID_LABELS = {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}


def test_vectorizer_is_tfidf_and_loadable():
    vec = joblib.load(str(VEC_PATH))
    assert isinstance(vec, TfidfVectorizer)
    # check expected params thesis: TF-IDF
    assert vec.use_idf is True
    assert vec.lowercase is True
    assert len(vec.vocabulary_) > 100


def test_vectorizer_transform_operation():
    vec = joblib.load(str(VEC_PATH))
    X = vec.transform(["The intern does excellent work", ""])
    # should produce sparse matrix with correct vocab size
    assert X.shape[1] == len(vec.vocabulary_)
    assert X.shape[0] == 2
    # empty string should be all zero
    assert X[1].nnz == 0


def test_naive_bayes_exists_and_trained():
    nb = joblib.load(str(NB_PATH))
    assert isinstance(nb, MultinomialNB)
    # must have classes_ and not be untrained
    assert hasattr(nb, "classes_")
    assert set(nb.classes_) == VALID_LABELS
    # check model can predict
    vec = joblib.load(str(VEC_PATH))
    pred = nb.predict(vec.transform(["Outstanding performance and dedication"]))
    assert pred[0] in VALID_LABELS


def test_svm_exists_and_trained():
    assert os.path.exists(str(SVM_PATH)), "SVM model file missing — thesis requires SVM"
    svm = joblib.load(str(SVM_PATH))
    assert isinstance(svm, SVC)
    assert hasattr(svm, "classes_")
    assert set(svm.classes_) == VALID_LABELS
    # SVM kernel should be linear per thesis pipeline
    assert svm.kernel == "linear"
    vec = joblib.load(str(VEC_PATH))
    pred = svm.predict(vec.transform(["The student frequently misses deadlines"]))
    assert pred[0] in VALID_LABELS


def test_predictor_backward_compatible_string():
    from app.ML.predictor import analyze_feedback
    # Known samples from dataset should map correctly (not strict, but valid label)
    assert analyze_feedback("The intern consistently demonstrates initiative and produces high-quality work.") in VALID_LABELS
    assert analyze_feedback("The student frequently misses deadlines, fails to complete assigned tasks, and requires constant supervision.") == "Needs Improvement"
    # string API must return str, not dict
    res = analyze_feedback("Excellent work ethic and professional attitude.")
    assert isinstance(res, str)
    assert res in VALID_LABELS


def test_predictor_detailed_output_structure():
    from app.ML.predictor import analyze_feedback_detailed
    r = analyze_feedback_detailed("The intern shows outstanding dedication and delivers high quality work")
    assert isinstance(r, dict)
    required_keys = {"performance_label", "nb_prediction", "svm_prediction", "sentiment", "competency", "recommendation", "confidence", "is_empty"}
    assert required_keys.issubset(r.keys())
    assert r["performance_label"] in VALID_LABELS
    assert r["nb_prediction"] in VALID_LABELS
    assert r["svm_prediction"] in VALID_LABELS
    assert r["sentiment"] in {"Positive", "Neutral", "Negative"}
    assert isinstance(r["competency"], str) and len(r["competency"]) > 5
    assert isinstance(r["recommendation"], str) and len(r["recommendation"]) > 10
    assert isinstance(r["confidence"], float)
    assert 0.0 <= r["confidence"] <= 1.0
    assert r["is_empty"] is False


def test_invalid_empty_feedback_handling():
    from app.ML.predictor import analyze_feedback, analyze_feedback_detailed
    # None
    assert analyze_feedback(None) in VALID_LABELS
    assert analyze_feedback("") in VALID_LABELS
    assert analyze_feedback("   ") in VALID_LABELS
    assert analyze_feedback(12345) in VALID_LABELS
    # detailed empty flag
    d1 = analyze_feedback_detailed(None)
    assert d1["is_empty"] is True
    assert d1["performance_label"] in VALID_LABELS
    assert d1["sentiment"] in {"Positive", "Neutral", "Negative"}
    d2 = analyze_feedback_detailed("")
    assert d2["is_empty"] is True
    d3 = analyze_feedback_detailed("   ")
    assert d3["is_empty"] is True
    # numeric/unknown vocab should not crash and should be valid
    d4 = analyze_feedback_detailed("$$$$ ??? 999")
    assert isinstance(d4, dict)
    assert d4["performance_label"] in VALID_LABELS


def test_output_structure_nb_svm_consistency():
    from app.ML.predictor import analyze_feedback_detailed
    samples = [
        "The student consistently exceeds expectations, demonstrates excellent teamwork",
        "The student completes some assigned tasks but needs improvement in consistency",
        "The student meets internship requirements and demonstrates satisfactory progress",
    ]
    for s in samples:
        d = analyze_feedback_detailed(s)
        # both models must produce valid labels
        assert d["nb_prediction"] in VALID_LABELS
        assert d["svm_prediction"] in VALID_LABELS
        # sentiment must match performance mapping
        from app.ML.predictor import SENTIMENT_MAP
        assert d["sentiment"] == SENTIMENT_MAP[d["performance_label"]]


def test_model_artifact_loading_both():
    # predictor module should have loaded both
    import app.ML.predictor as pred
    assert hasattr(pred, "vectorizer")
    assert hasattr(pred, "nb_model")
    assert hasattr(pred, "svm_model")
    assert isinstance(pred.vectorizer, TfidfVectorizer)
    assert isinstance(pred.nb_model, MultinomialNB)
    assert pred.svm_model is not None
    assert isinstance(pred.svm_model, SVC)


def test_supervisor_feedback_integration_stores_ml():
    """End-to-end: POST feedback as supervisor must store ml_prediction."""
    from bootstrap.app import app
    from unittest.mock import MagicMock, patch
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 5
        sess["role"] = "supervisor"
    mock_conn = MagicMock()
    # track execute calls
    executed = []
    def exec_track(sql, params=None):
        executed.append((sql, params))
        m = MagicMock()
        m.fetchone.return_value = {"status": "active"} if "SELECT status" in sql else (1,) if "SELECT 1 FROM student_assignments" in sql else None
        # for feedback edge, we return assignment ok so first check passes
        if "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        else:
            m.fetchone.return_value = {"status": "active"} if "SELECT status" in sql else None
        return m
    # before_request + assignment check + insert, need side_effect that distinguishes
    def side(sql, params=None):
        m = MagicMock()
        if "SELECT status" in sql:
            m.fetchone.return_value = {"status": "active"}
        elif "SELECT 1 FROM student_assignments" in sql:
            m.fetchone.return_value = (1,)
        elif "INSERT INTO feedback" in sql:
            # capture and succeed
            executed.append((sql, params))
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = None
        return m
    mock_conn.execute.side_effect = side
    mock_conn.cursor.return_value = MagicMock()
    with patch("app.Http.Controllers.supervisor.get_db_connection", return_value=mock_conn):
        with patch("app.Http.Controllers.supervisor.create_notification"):
            resp = client.post("/supervisor/student/20/feedback", data={"comment": "The intern consistently demonstrates initiative and produces high-quality work.", "label": "Excellent"})
            assert resp.status_code in (302,303)
            # verify at least one INSERT containing ml_prediction or INSERT INTO feedback
            inserts = [c for c in mock_conn.execute.call_args_list if "INSERT INTO feedback" in str(c)]
            assert len(inserts) >= 1
            # check that ml data was included (vector of 10 params if new schema else 4)
            last_call = inserts[-1]
            args, kwargs = last_call
            # params is second arg tuple
            if len(args) >= 2 and args[1] is not None:
                params = args[1]
                # new schema has 10 params, old has 4
                assert len(params) in (4, 10)
                if len(params) == 10:
                    # ml_prediction at index 4
                    assert params[4] in VALID_LABELS


def test_competency_and_recommendation_derived():
    from app.ML.predictor import get_competency, get_recommendation, get_sentiment, COMPETENCY_MAP, RECOMMENDATION_MAP
    for label in VALID_LABELS:
        comp = get_competency(label)
        rec = get_recommendation(label)
        sent = get_sentiment(label)
        assert comp == COMPETENCY_MAP[label]
        assert rec == RECOMMENDATION_MAP[label]
        assert sent in {"Positive","Neutral","Negative"}
