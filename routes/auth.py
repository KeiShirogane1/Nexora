from flask import Blueprint, render_template, request, redirect, url_for, session
from database.db import get_db_connection


auth = Blueprint("auth", __name__)


@auth.route("/logout")
def logout():
    session.clear()
    return redirect("/")


def get_user(username, password):
    conn = get_db_connection()
    try:
        user = conn.execute("""
            SELECT * FROM users
            WHERE username = ? AND password = ?
        """, (username, password)).fetchone()
        return user
    finally:
        conn.close()


@auth.route("/")
def welcome():
    return render_template("welcome.html")


@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        user = get_user(username, password)

        if user:
            role = user["role"]

            # Pending accounts must be approved by an admin first.
            if role == "pending":
                return "Your account is pending approval. Please contact an administrator.", 403

            session["user_id"] = user["id"]
            session["role"] = role

            if role == "student":
                return redirect(url_for("student.student_dashboard"))
            elif role == "supervisor":
                return redirect(url_for("supervisor.supervisor_dashboard"))
            elif role == "admin":
                return redirect(url_for("admin.admin_dashboard"))

        return "Invalid credentials ❌"

    return render_template("auth/login.html")


@auth.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if not username:
            return "Username is required ❌"

        if password != confirm_password:
            return "Passwords do not match ❌"

        if len(password) < 6:
            return "Password must be at least 6 characters ❌"

        conn = get_db_connection()
        try:
            existing_user = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()

            if existing_user:
                return "Username already exists ❌"

            conn.execute("""
                INSERT INTO users (username, password, role)
                VALUES (?, ?, 'pending')
            """, (username, password))
            conn.commit()
        finally:
            conn.close()

        return redirect("/login")

    return render_template("auth/signup.html")
