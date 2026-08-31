"""
app/__init__.py
Laravel-inspired app package.
Exposes `app` for backward compatibility: `from app import app`.
Actual Flask app lives in bootstrap/app.py to keep factory clean.
"""

# Re-export for compatibility; bootstrap/app.py is source of truth
try:
    from bootstrap.app import app  # noqa: F401
except Exception:
    # During initial import before bootstrap is ready, expose placeholder
    app = None
