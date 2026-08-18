import os
import joblib


# Get the current folder (ml/)
BASE_DIR = os.path.dirname(__file__)


# Load the trained model
model = joblib.load(
    os.path.join(BASE_DIR, "model", "performance_model.pkl")
)

# Load the vectorizer
vectorizer = joblib.load(
    os.path.join(BASE_DIR, "model", "vectorizer.pkl")
)


def analyze_feedback(feedback_text):
    """
    Predicts the performance label from supervisor feedback.
    """

    transformed = vectorizer.transform([feedback_text])

    prediction = model.predict(transformed)

    return prediction[0]