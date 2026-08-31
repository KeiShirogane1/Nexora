import os

from dotenv import load_dotenv

load_dotenv()

import secrets
from pathlib import Path
from flask import Flask
from routes.auth import auth
from routes.password import password
from routes.student import student
from routes.supervisor import supervisor
from routes.admin import admin
from init_db import initialize_database

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)

# Use a Render environment variable in production and keep a local fallback.
app.secret_key = (
    os.environ.get("SECRET_KEY")
    or secrets.token_urlsafe(48)
)
UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

# Make sure a fresh Render database has all required tables before requests arrive.
initialize_database()

app.register_blueprint(auth)
app.register_blueprint(password)
app.register_blueprint(student)
app.register_blueprint(supervisor)
app.register_blueprint(admin)


if __name__ == "__main__":
    app.run(debug=True)
