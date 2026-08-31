"""
run.py
Laravel-inspired entry point for Nexora.
Keeps Render and local development runnable via `python run.py` or `gunicorn run:app`.
Preserves bootstrap/app.py as source of truth.
"""
from bootstrap.app import app

if __name__ == "__main__":
    app.run(debug=True)
