"""
app/__init__.py
Laravel-inspired app package.

The actual Flask application lives in bootstrap/app.py. Keep `from app import app`
working for backward compatibility without importing bootstrap.app during normal
package imports such as `app.Models.db`.
"""

__all__ = ["app"]


def __getattr__(name):
    if name == "app":
        from bootstrap.app import app as flask_app

        return flask_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
