import os
import secrets
from pathlib import Path

from dotenv import load_dotenv


# ==========================
# LOAD ENVIRONMENT
# ==========================

BASE_DIR = Path(__file__).resolve().parent.parent


load_dotenv(
    BASE_DIR / ".env"
)


# BREVO config is read via os.environ / config.settings; do not log secrets.



# ==========================
# FLASK IMPORTS
# ==========================

from flask import (
    Flask,
    send_from_directory,
    session
)


from app.Http.Controllers.auth import auth
from app.Http.Controllers.password import password
from app.Http.Controllers.student import student
from app.Http.Controllers.supervisor import supervisor
from app.Http.Controllers.admin import admin
from app.Http.Controllers.notifications import notifications_bp


from scripts.init_db import initialize_database


from app.Services.notification_service import (
    get_user_notifications,
    get_unread_count
)



# ==========================
# CREATE APP
# ==========================


app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "resources" / "views"),
    static_folder=str(BASE_DIR / "resources" / "assets"),
    static_url_path="/static"
)



# ==========================
# SECURITY — SECRET & SESSION
# ==========================

# SECRET_KEY must be stable. Use env var in production; dev fallback is fixed
# (do NOT generate random per-boot which invalidates sessions).
_dev_fallback = "dev-secret-key-change-me-not-for-production"
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    # In production, require explicit SECRET_KEY
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("NEXORA_ENV") == "production":
        raise RuntimeError("SECRET_KEY must be set in production")
    _secret = _dev_fallback

app.secret_key = _secret
app.config["SECRET_KEY"] = _secret

# Secure session cookies — Lax by default, Secure only on HTTPS/production
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Enable Secure cookies only when explicitly requested or in production
_secure_cookies = os.environ.get("SESSION_COOKIE_SECURE", "")
if _secure_cookies.lower() in ("1", "true", "yes"):
    app.config["SESSION_COOKIE_SECURE"] = True
elif os.environ.get("FLASK_ENV") == "production" or os.environ.get("NEXORA_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True
else:
    app.config["SESSION_COOKIE_SECURE"] = False

# Upload hardening — max 5MB per file
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# Flask debug — never on by default; enable explicitly via FLASK_DEBUG=1 or NEXORA_DEBUG=1
_flask_debug = os.environ.get("FLASK_DEBUG", os.environ.get("NEXORA_DEBUG", "0"))
app.debug = _flask_debug.lower() in ("1", "true", "yes")

# CSRF protection — Flask-WTF, protects POST/PUT/PATCH/DELETE including JSON via header X-CSRFToken
app.config["WTF_CSRF_ENABLED"] = True
# No time limit for token (keeps simple for thesis demo); still one-time per session
app.config["WTF_CSRF_TIME_LIMIT"] = None
try:
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect(app)
    # Exempt is not used; JSON fetch must send X-CSRFToken header
except ImportError:
    csrf = None

# Security headers — X-Content-Type-Options, X-Frame-Options, Referrer-Policy, CSP (allow inline for existing app), HSTS for HTTPS
@app.after_request
def _set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # CSP: allow self + inline (existing app has many inline scripts/styles) + CDN
    # Do not break existing app — allow unsafe-inline for scripts/styles
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "img-src 'self' data: https:; "
        "font-src 'self' https: data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["Content-Security-Policy"] = csp
    # HSTS only on HTTPS/production
    if app.config.get("SESSION_COOKIE_SECURE"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response



# ==========================
# UPLOAD SETTINGS
# ==========================


UPLOAD_FOLDER = BASE_DIR / "storage" / "uploads"


UPLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


app.config["UPLOAD_FOLDER"] = str(
    UPLOAD_FOLDER
)



# ==========================
# SERVE FILES
# ==========================


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):

    return send_from_directory(
        str(BASE_DIR / "storage" / "uploads"),
        filename
    )



# ==========================
# PROFILE PICTURE UPLOAD
# ==========================


PROFILE_UPLOAD_FOLDER = (
    UPLOAD_FOLDER / "profile_pictures"
)


PROFILE_UPLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


app.config["PROFILE_UPLOAD_FOLDER"] = str(
    PROFILE_UPLOAD_FOLDER
)



@app.route("/uploads/profile_pictures/<filename>")
def profile_picture(filename):

    return send_from_directory(
        app.config["PROFILE_UPLOAD_FOLDER"],
        filename
    )



# ==========================
# HEALTH CHECK — for Render, no auth
# ==========================

@app.route("/health")
def health():
    return {"status": "ok"}, 200

# ==========================
# DATABASE INITIALIZATION
# ==========================


initialize_database()



# ==========================
# REGISTER BLUEPRINTS
# ==========================


app.register_blueprint(auth)

app.register_blueprint(password)

app.register_blueprint(student)

app.register_blueprint(supervisor)

app.register_blueprint(admin)

app.register_blueprint(notifications_bp)



# ==========================
# NOTIFICATION SYSTEM
# ==========================


@app.context_processor
def inject_notifications():

    if "user_id" in session:
        try:
            return {
                "notifications": get_user_notifications(
                    session["user_id"], limit=20
                ),
                "unread_count": get_unread_count(
                    session["user_id"]
                )
            }
        except Exception as e:
            print("inject_notifications failed:", e)
            return {"notifications": [], "unread_count": 0}

    return {"notifications": [], "unread_count": 0}



# ==========================
# RUN APP
# ==========================


if __name__ == "__main__":

    app.run(
        debug=app.debug
    )