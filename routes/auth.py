from flask import Blueprint, render_template, request, redirect, url_for, session

from database.db import get_db_connection
from security.password_security import hash_password, verify_password

auth = Blueprint("auth", __name__)


@auth.route("/logout")
def logout():
    session.clear()
    return redirect("/")


def get_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE username = ?
            OR email = ?
            """,
            (
                username,
                email
            )
        )

        user = cursor.fetchone()

        if not user:
            return None

        stored_password = user["password"]

        if not verify_password(
            stored_password,
            password
        ):
            return None

        return user

    finally:
        cursor.close()
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

            session["user_id"] = user["id"]
            session["role"] = role

            if role == "student":
                return redirect(
                    url_for("student.student_dashboard")
                )

            elif role == "supervisor":
                return redirect(
                    url_for("supervisor.supervisor_dashboard")
                )

            elif role == "admin":
                return redirect(
                    url_for("admin.admin_dashboard")
                )

        # Save the warning temporarily.
        session["login_error"] = (
            "Invalid username or password ❌"
        )

        session["login_username"] = username

        # Redirect back to login instead of directly
        # returning the failed POST page.
        return redirect(
            url_for("auth.login")
        )

    # These values are shown only once.
    error = session.pop(
        "login_error",
        None
    )

    entered_username = session.pop(
        "login_username",
        ""
    )

    return render_template(
        "auth/login.html",
        error=error,
        entered_username=entered_username
    )

@auth.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":
        username = request.form["username"].strip()

        email = (
            request.form["email"]
            .strip()
            .lower()
        )

        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        # Validate passwords match
        if password != confirm_password:
            return "Passwords do not match ❌"

        # Validate password length
        if len(password) < 8:
            return "Password must be at least 8 characters ❌"

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Check if username OR email already exists
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE username = ?
                   OR email = ?
                """,
                (
                    username,
                    email
                )
            )

            if cursor.fetchone():
                return "Username or email already exists ❌"

            # Securely hash password
            password_hash = hash_password(password)

            # New accounts remain pending
            cursor.execute(
                """
                INSERT INTO users (
                    username,
                    email,
                    password,
                    role
                )
                VALUES (?, ?, ?, 'pending')
                """,
                (
                    username,
                    email,
                    password_hash
                )
            )

            conn.commit()

        finally:
            cursor.close()
            conn.close()

        return redirect("/login")

    return render_template("auth/signup.html")