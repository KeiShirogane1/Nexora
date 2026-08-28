import os
<<<<<<< Updated upstream
<<<<<<< Updated upstream
from pathlib import Path
from flask import Flask
=======
=======
>>>>>>> Stashed changes
import secrets
from pathlib import Path

from dotenv import load_dotenv


# ==========================
# LOAD ENVIRONMENT
# ==========================

BASE_DIR = Path(__file__).resolve().parent


load_dotenv(
    BASE_DIR / ".env"
)


print(
    "BREVO CHECK:",
    os.environ.get("BREVO_API_KEY")
)



# ==========================
# FLASK IMPORTS
# ==========================

from flask import (
    Flask,
    send_from_directory,
    session
)


<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
from routes.auth import auth
from routes.student import student
from routes.supervisor import supervisor
from routes.admin import admin
from routes.notifications import notifications_bp


from init_db import initialize_database


<<<<<<< Updated upstream
<<<<<<< Updated upstream
BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)

# Use a Render environment variable in production and keep a local fallback.
app.secret_key = os.environ.get("SECRET_KEY", "nexora_secret_key")

UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
=======
from services.notification_service import (
    get_user_notifications,
    get_unread_count
)



# ==========================
# CREATE APP
# ==========================


app = Flask(__name__)

>>>>>>> Stashed changes


# ==========================
# SECURITY
# ==========================


app.secret_key = (

    os.environ.get("SECRET_KEY")

    or secrets.token_urlsafe(48)

)



# ==========================
# UPLOAD SETTINGS
# ==========================


UPLOAD_FOLDER = BASE_DIR / "uploads"


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
        "uploads",
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
# DATABASE INITIALIZATION
# ==========================


=======
from services.notification_service import (
    get_user_notifications,
    get_unread_count
)



# ==========================
# CREATE APP
# ==========================


app = Flask(__name__)



# ==========================
# SECURITY
# ==========================


app.secret_key = (

    os.environ.get("SECRET_KEY")

    or secrets.token_urlsafe(48)

)



# ==========================
# UPLOAD SETTINGS
# ==========================


UPLOAD_FOLDER = BASE_DIR / "uploads"


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
        "uploads",
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
# DATABASE INITIALIZATION
# ==========================


>>>>>>> Stashed changes
initialize_database()



# ==========================
# REGISTER BLUEPRINTS
# ==========================


app.register_blueprint(auth)
<<<<<<< Updated upstream
<<<<<<< Updated upstream
=======

app.register_blueprint(password)

>>>>>>> Stashed changes
=======

app.register_blueprint(password)

>>>>>>> Stashed changes
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
        debug=True
    )