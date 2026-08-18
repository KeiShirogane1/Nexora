from ml.predictor import analyze_feedback

feedback = (
    "The intern consistently demonstrates initiative and "
    "produces high-quality work."
)

print(
    analyze_feedback(feedback)
)