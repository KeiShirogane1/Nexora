"""Thesis-ready evaluation for Naive Bayes vs Linear SVM on feedback dataset."""

import csv
import os
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import LinearSVC

# Dataset path relative to this file: app/Services -> app/ML/dataset/feedback_dataset.csv
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = BASE_DIR / "ML" / "dataset" / "feedback_dataset.csv"
# Fallback for different relative layouts
ALT_DATASET = Path(__file__).resolve().parent.parent.parent / "app" / "ML" / "dataset" / "feedback_dataset.csv"

EXPECTED_LABELS_SET = {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}


def _resolve_dataset(path=None):
    if path is not None:
        return Path(path)
    # Prefer DEFAULT_DATASET if exists, else ALT
    if DEFAULT_DATASET.exists():
        return DEFAULT_DATASET
    if ALT_DATASET.exists():
        return ALT_DATASET
    return DEFAULT_DATASET


def _empty_result(labels=None):
    return {
        "sample_count": 0,
        "labels": labels if labels is not None else [],
        "naive_bayes": {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        "svm": {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0},
    }


def evaluate_feedback_models(dataset_path=None):
    """
    Evaluate existing feedback dataset with TF-IDF + Naive Bayes vs Linear SVM.

    Uses a reproducible train/test split (80/20, stratified, random_state=42)
    and weighted averaging for multiclass metrics with zero_division=0.

    Handles missing/invalid dataset gracefully without raising.
    """
    dataset = _resolve_dataset(dataset_path)

    # Handle missing file gracefully
    if not dataset.exists():
        return _empty_result()

    texts = []
    labels = []
    try:
        with dataset.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Expect columns feedback,label
            if reader.fieldnames is None:
                return _empty_result()
            # Normalize fieldnames
            has_feedback = "feedback" in reader.fieldnames
            has_label = "label" in reader.fieldnames
            if not has_feedback or not has_label:
                return _empty_result()
            for row in reader:
                try:
                    feedback = (row.get("feedback") or "").strip()
                    label = (row.get("label") or "").strip()
                    if not feedback or not label:
                        continue
                    # Only keep expected labels but allow any to avoid data loss
                    texts.append(feedback)
                    labels.append(label)
                except Exception:
                    continue
    except Exception:
        return _empty_result()

    sample_count = len(texts)
    if sample_count == 0:
        return _empty_result()

    # Unique labels present in dataset (sorted for determinism)
    unique_labels = sorted(set(labels))

    # Require at least 2 labels and enough samples for split
    if len(unique_labels) < 2:
        return {
            "sample_count": sample_count,
            "labels": unique_labels,
            "naive_bayes": {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0},
            "svm": {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        }

    # If sample count too small for stratified split, fallback to simple split
    try:
        vectorizer = TfidfVectorizer(lowercase=True, stop_words="english")
        X = vectorizer.fit_transform(texts)
        y = labels

        # Use stratify if each class has at least 2 members
        from collections import Counter
        counts = Counter(y)
        can_stratify = all(c >= 2 for c in counts.values()) and sample_count >= 10
        stratify = y if can_stratify else None

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=stratify
        )

        if len(y_test) == 0 or len(y_train) == 0:
            return _empty_result(unique_labels)

        # Train Naive Bayes
        nb = MultinomialNB()
        nb.fit(X_train, y_train)
        nb_pred = nb.predict(X_test)

        # Train Linear SVM
        svm = LinearSVC(random_state=42)
        svm.fit(X_train, y_train)
        svm_pred = svm.predict(X_test)

        def _metrics(y_true, y_pred):
            return {
                "accuracy": float(accuracy_score(y_true, y_pred)),
                "precision": float(precision_score(y_true, y_pred, average="weighted", zero_division=0)),
                "recall": float(recall_score(y_true, y_pred, average="weighted", zero_division=0)),
                "f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
            }

        nb_metrics = _metrics(y_test, nb_pred)
        svm_metrics = _metrics(y_test, svm_pred)

        # Clamp to [0,1] just in case
        for m in (nb_metrics, svm_metrics):
            for k in list(m.keys()):
                v = m[k]
                if v < 0:
                    m[k] = 0.0
                elif v > 1:
                    m[k] = 1.0

        return {
            "sample_count": sample_count,
            "labels": unique_labels,
            "naive_bayes": nb_metrics,
            "svm": svm_metrics,
        }
    except Exception:
        # Any training/evaluation failure should be graceful
        return {
            "sample_count": sample_count,
            "labels": unique_labels,
            "naive_bayes": {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0},
            "svm": {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0},
        }
