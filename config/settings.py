"""
config/settings.py
Laravel-inspired settings module for Nexora.

Mirrors Flask config but keeps .env loading centralized.
Preserve existing behavior: SECRET_KEY fallback, upload paths, etc.
"""
import os
from pathlib import Path

# Project root (one level up from config/)
BASE_DIR = Path(__file__).resolve().parent.parent

_dev_fallback = "dev-secret-key-change-me-not-for-production"
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("NEXORA_ENV") == "production":
        raise RuntimeError("SECRET_KEY must be set in production")
    SECRET_KEY = _dev_fallback

# Upload paths (storage/uploads) - mirrors bootstrap/app.py logic
UPLOAD_FOLDER = str(BASE_DIR / "storage" / "uploads")
PROFILE_UPLOAD_FOLDER = str(BASE_DIR / "storage" / "uploads" / "profile_pictures")

# Brevo / Email
BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "")

# Database (handled via app.Models.db)
