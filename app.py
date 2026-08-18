from flask import Flask
from routes.auth import auth
from routes.student import student
from routes.supervisor import supervisor
from routes.admin import admin

app = Flask(__name__)

# REQUIRED for session handling
app.secret_key = "nexora_secret_key"

import os

UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

app.register_blueprint(auth)
app.register_blueprint(student)
app.register_blueprint(supervisor)
app.register_blueprint(admin)

if __name__ == "__main__":
    app.run(debug=True)