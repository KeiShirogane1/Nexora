import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

from flask import Flask, send_from_directory, session

from app.Http.Controllers.auth import auth
from app.Http.Controllers.password import password
from app.Http.Controllers.student import student
from app.Http.Controllers.supervisor import supervisor
from app.Http.Controllers.admin import admin
from app.Http.Controllers.classroom import classroom
from app.Http.Controllers.classwork import classwork
from app.Http.Controllers.student_classwork import student_classwork
from app.Http.Controllers.classwork_submissions import classwork_submissions
from app.Http.Controllers.notifications import notifications_bp

from scripts.init_db import initialize_database
from app.Services.classroom_service import ensure_classroom_schema
from app.Services.classwork_submission_service import ensure_classwork_submission_schema
from app.Services.notification_service import get_user_notifications, get_unread_count

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "resources" / "views"),
    static_folder=str(BASE_DIR / "resources" / "assets"),
    static_url_path="/static"
)

_dev_fallback = "dev-secret-key-change-me-not-for-production"
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("NEXORA_ENV") == "production":
        raise RuntimeError("SECRET_KEY must be set in production")
    _secret = _dev_fallback

app.secret_key = _secret
app.config["SECRET_KEY"] = _secret
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes") or os.environ.get("FLASK_ENV") == "production" or os.environ.get("NEXORA_ENV") == "production"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

_debug = os.environ.get("FLASK_DEBUG", os.environ.get("NEXORA_DEBUG", "0"))
app.debug = _debug.lower() in ("1", "true", "yes")
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_TIME_LIMIT"] = None
try:
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect(app)
except ImportError as _csrf_err:
    if app.config.get("WTF_CSRF_ENABLED"):
        raise RuntimeError("Flask-WTF is required for CSRF protection but is not installed. Install with: pip install flask-wtf") from _csrf_err
    csrf = None

@app.after_request
def _set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; img-src 'self' data: https:; font-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'"
    if app.config.get("SESSION_COOKIE_SECURE"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

UPLOAD_FOLDER = BASE_DIR / "storage" / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

PROFILE_UPLOAD_FOLDER = UPLOAD_FOLDER / "profile_pictures"
PROFILE_UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config["PROFILE_UPLOAD_FOLDER"] = str(PROFILE_UPLOAD_FOLDER)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(str(UPLOAD_FOLDER), filename)

@app.route("/uploads/profile_pictures/<filename>")
def profile_picture(filename):
    return send_from_directory(app.config["PROFILE_UPLOAD_FOLDER"], filename)

@app.route("/health")
def health():
    return {"status": "ok"}, 200

initialize_database()
ensure_classroom_schema()
ensure_classwork_submission_schema()

app.register_blueprint(auth)
app.register_blueprint(password)
app.register_blueprint(student)
app.register_blueprint(student_classwork)
app.register_blueprint(supervisor)
app.register_blueprint(admin)
app.register_blueprint(classroom)
app.register_blueprint(classwork)
app.register_blueprint(classwork_submissions)
app.register_blueprint(notifications_bp)

@app.context_processor
def inject_notifications():
    if "user_id" in session:
        try:
            return {"notifications": get_user_notifications(session["user_id"], limit=20), "unread_count": get_unread_count(session["user_id"])}
        except Exception as e:
            print("inject_notifications failed:", e)
            return {"notifications": [], "unread_count": 0}
    return {"notifications": [], "unread_count": 0}

if __name__ == "__main__":
    app.run(debug=app.debug)
