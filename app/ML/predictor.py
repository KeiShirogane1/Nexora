import os
import re
import joblib

BASE_DIR = os.path.dirname(__file__)
MODEL_DIR = os.path.join(BASE_DIR, "model")

# -------------------------------------------------------------------
# Load artifacts (TF-IDF + NB + SVM)
# -------------------------------------------------------------------
vectorizer = joblib.load(os.path.join(MODEL_DIR, "vectorizer.pkl"))

# Primary model: Naive Bayes (backward-compatible name performance_model.pkl)
model = joblib.load(os.path.join(MODEL_DIR, "performance_model.pkl"))
nb_model = model  # alias

# SVM model (thesis requirement) — optional if artifact missing
svm_model = None
svm_path = os.path.join(MODEL_DIR, "svm_model.pkl")
if os.path.exists(svm_path):
    try:
        svm_model = joblib.load(svm_path)
    except Exception:
        svm_model = None

# -------------------------------------------------------------------
# Thesis-aligned label mappings
# Dataset limitation note:
#   feedback_dataset.csv provides ONLY performance labels:
#   [Excellent, Very Satisfactory, Satisfactory, Fair, Needs Improvement]
#   No explicit sentiment/competency/recommendation labels exist.
#   Sentiment, competency, and recommendation are therefore DERIVED
#   deterministically from the performance label (heuristic mapping)
#   — NOT from a separately trained competency classifier.
# -------------------------------------------------------------------
VALID_LABELS = {"Excellent", "Very Satisfactory", "Satisfactory", "Fair", "Needs Improvement"}

SENTIMENT_MAP = {
    "Excellent": "Positive",
    "Very Satisfactory": "Positive",
    "Satisfactory": "Neutral",
    "Fair": "Negative",
    "Needs Improvement": "Negative",
}

COMPETENCY_MAP = {
    "Excellent": "Outstanding Competency",
    "Very Satisfactory": "Strong Competency",
    "Satisfactory": "Adequate Competency",
    "Fair": "Developing Competency",
    "Needs Improvement": "Needs Significant Development",
}

RECOMMENDATION_MAP = {
    "Excellent": "Continue excellent performance; consider leadership opportunities and advanced responsibilities.",
    "Very Satisfactory": "Maintain strong performance; minor coaching to reach excellent level.",
    "Satisfactory": "Meets expectations; targeted skill development and consistent follow-through recommended.",
    "Fair": "Needs improvement in consistency, communication, and time management; additional supervision and coaching required.",
    "Needs Improvement": "Requires significant intervention, close supervision, and a structured improvement plan.",
}

# -------------------------------------------------------------------
# Preprocessing
# -------------------------------------------------------------------
def _preprocess(text):
    """Clean text deterministically. Handles None/non-string gracefully."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    # lowercasing is also done by vectorizer but we clean punctuation here
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _get_sentiment(label):
    return SENTIMENT_MAP.get(label, "Neutral")


def _get_competency(label):
    return COMPETENCY_MAP.get(label, "Adequate Competency")


def _get_recommendation(label):
    return RECOMMENDATION_MAP.get(label, "Continue monitoring performance.")


def _predict_label(cleaned_text):
    """
    Core prediction using NB primary; SVM used for comparison if available.
    Returns tuple (nb_pred, svm_pred, chosen_pred, confidence)
    cleaned_text is already lowercased/cleaned. Vectorizer will tokenize it.
    """
    # Vectorizer expects raw string; passing cleaned is fine
    transformed = vectorizer.transform([cleaned_text])
    # Handle all-zero vector (empty/unknown vocab): fallback to neutral
    if transformed.nnz == 0:
        # no known tokens — default to middle label
        return "Satisfactory", "Satisfactory", "Satisfactory", 0.0

    nb_pred = nb_model.predict(transformed)[0]

    svm_pred = None
    if svm_model is not None:
        try:
            svm_pred = svm_model.predict(transformed)[0]
        except Exception:
            svm_pred = None
    if svm_pred is None:
        svm_pred = nb_pred

    # Confidence from NB predict_proba if available
    confidence = 0.0
    try:
        if hasattr(nb_model, "predict_proba"):
            proba = nb_model.predict_proba(transformed)[0]
            # proba aligned with nb_model.classes_
            confidence = float(max(proba))
    except Exception:
        confidence = 0.0

    # Primary thesis decision: Naive Bayes is authoritative for performance_label
    # SVM is provided for comparison / thesis compliance
    chosen = nb_pred
    return nb_pred, svm_pred, chosen, confidence


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------
def analyze_feedback(feedback_text):
    """
    Backward-compatible performance prediction.
    Returns a string label (one of VALID_LABELS).
    Handles None/empty/invalid gracefully without raising.
    """
    cleaned = _preprocess(feedback_text)
    if not cleaned:
        return "Satisfactory"
    try:
        _, _, chosen, _ = _predict_label(cleaned)
        # ensure return is plain str
        return str(chosen)
    except Exception:
        return "Satisfactory"


def analyze_feedback_detailed(feedback_text):
    """
    Thesis-aligned full analysis.
    Returns dict:
      {
        performance_label: str,
        nb_prediction: str,
        svm_prediction: str,
        sentiment: str,            # Positive / Neutral / Negative
        competency: str,            # competency assessment
        recommendation: str,
        confidence: float,
        is_empty: bool
      }
    Never raises on invalid/empty input.
    """
    cleaned = _preprocess(feedback_text)
    is_empty = not bool(cleaned)
    if is_empty:
        label = "Satisfactory"
        return {
            "performance_label": label,
            "nb_prediction": label,
            "svm_prediction": label,
            "sentiment": _get_sentiment(label),
            "competency": _get_competency(label),
            "recommendation": _get_recommendation(label),
            "confidence": 0.0,
            "is_empty": True,
        }
    try:
        nb_pred, svm_pred, chosen, conf = _predict_label(cleaned)
        return {
            "performance_label": str(chosen),
            "nb_prediction": str(nb_pred),
            "svm_prediction": str(svm_pred),
            "sentiment": _get_sentiment(str(chosen)),
            "competency": _get_competency(str(chosen)),
            "recommendation": _get_recommendation(str(chosen)),
            "confidence": float(conf),
            "is_empty": False,
        }
    except Exception:
        label = "Satisfactory"
        return {
            "performance_label": label,
            "nb_prediction": label,
            "svm_prediction": label,
            "sentiment": _get_sentiment(label),
            "competency": _get_competency(label),
            "recommendation": _get_recommendation(label),
            "confidence": 0.0,
            "is_empty": False,
        }


# Aliases for integration callers
def get_sentiment(label):
    return _get_sentiment(label)

def get_competency(label):
    return _get_competency(label)

def get_recommendation(label):
    return _get_recommendation(label)
