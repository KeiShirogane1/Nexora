"""
routes/web.py
Laravel-inspired web routes registration.
Preserves all existing blueprint endpoint names.
"""
from app.Http.Controllers.auth import auth
from app.Http.Controllers.password import password
from app.Http.Controllers.student import student
from app.Http.Controllers.supervisor import supervisor
from app.Http.Controllers.admin import admin


def register_web_routes(app):
    # Order preserved from original bootstrap/app.py
    app.register_blueprint(auth)
    app.register_blueprint(password)
    app.register_blueprint(student)
    app.register_blueprint(supervisor)
    app.register_blueprint(admin)
