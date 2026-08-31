"""
routes/api.py
Laravel-inspired API routes registration.
Currently handles notifications; preserves endpoint names.
"""
from app.Http.Controllers.notifications import notifications_bp


def register_api_routes(app):
    app.register_blueprint(notifications_bp)
