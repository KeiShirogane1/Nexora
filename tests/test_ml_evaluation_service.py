import pathlib
import sys
import tempfile
import os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.Services.ml_evaluation_service import evaluate_feedback_models


EXPECTED_LABELS = {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}


def test_dataset_loads_and_sample_count():
    result = evaluate_feedback_models()
    assert result["sample_count"] > 0, "dataset should contain samples"
    assert isinstance(result["sample_count"], int)


def test_expected_five_labels_exist():
    result = evaluate_feedback_models()
    labels = result["labels"]
    assert isinstance(labels, list)
    assert set(labels) == EXPECTED_LABELS, f"labels mismatch: {labels}"
    assert len(labels) == 5


def test_nb_metrics_exist_and_between_0_and_1():
    result = evaluate_feedback_models()
    nb = result["naive_bayes"]
    for key in ("accuracy", "precision", "recall", "f1"):
        assert key in nb, f"missing nb metric {key}"
        val = nb[key]
        assert isinstance(val, float)
        assert 0.0 <= val <= 1.0, f"nb {key} out of range: {val}"


def test_svm_metrics_exist_and_between_0_and_1():
    result = evaluate_feedback_models()
    svm = result["svm"]
    for key in ("accuracy", "precision", "recall", "f1"):
        assert key in svm, f"missing svm metric {key}"
        val = svm[key]
        assert isinstance(val, float)
        assert 0.0 <= val <= 1.0, f"svm {key} out of range: {val}"


def test_all_four_metrics_exist_for_both_models():
    result = evaluate_feedback_models()
    for model in ("naive_bayes", "svm"):
        assert model in result
        metrics = result[model]
        assert set(metrics.keys()) == {"accuracy", "precision", "recall", "f1"}


def test_missing_dataset_handled_gracefully():
    missing = pathlib.Path(tempfile.gettempdir()) / "nexora_missing_dataset_12345.csv"
    # ensure missing
    if missing.exists():
        missing.unlink()
    result = evaluate_feedback_models(dataset_path=str(missing))
    assert result["sample_count"] == 0
    assert result["labels"] == []
    for model in ("naive_bayes", "svm"):
        for key in ("accuracy", "precision", "recall", "f1"):
            assert result[model][key] == 0.0


def test_invalid_dataset_handled_gracefully():
    # Create an invalid csv file (no correct columns)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        tmp.write("wrong,columns\n")
        tmp.write("a,b\n")
        tmp_path = tmp.name
    try:
        result = evaluate_feedback_models(dataset_path=tmp_path)
        assert result["sample_count"] == 0
        assert isinstance(result["labels"], list)
        for model in ("naive_bayes", "svm"):
            for key in ("accuracy", "precision", "recall", "f1"):
                assert 0.0 <= result[model][key] <= 1.0
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_predictor_not_modified():
    from app.ML import predictor as pred
    # Predictor should still expose expected API and VALID_LABELS
    assert hasattr(pred, "analyze_feedback")
    assert hasattr(pred, "analyze_feedback_detailed")
    assert hasattr(pred, "VALID_LABELS")
    assert pred.VALID_LABELS == EXPECTED_LABELS
    # Basic behavior unchanged
    assert pred.analyze_feedback("The student shows exceptional dedication to learning new skills") in EXPECTED_LABELS
    assert pred.analyze_feedback("") == "Satisfactory"
    assert pred.analyze_feedback(None) == "Satisfactory"
    detailed = pred.analyze_feedback_detailed("Excellent work and dedication")
    assert "sentiment" in detailed
    assert "competency" in detailed
    assert "recommendation" in detailed
    assert "confidence" in detailed
    assert "nb_prediction" in detailed
    assert "svm_prediction" in detailed


def test_result_structure_complete():
    result = evaluate_feedback_models()
    assert "sample_count" in result
    assert "labels" in result
    assert "naive_bayes" in result
    assert "svm" in result
    assert isinstance(result["sample_count"], int)
    assert isinstance(result["labels"], list)
    # Ensure metrics are finite numbers
    for model in ("naive_bayes", "svm"):
        for k, v in result[model].items():
            assert isinstance(v, float)
            assert v == v  # not NaN
