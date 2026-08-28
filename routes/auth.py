<<<<<<< Updated upstream
<<<<<<< Updated upstream
from flask import Blueprint, render_template, request, redirect, url_for, session
=======
=======
>>>>>>> Stashed changes
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

>>>>>>> Stashed changes
from database.db import get_db_connection

auth = Blueprint("auth", __name__)


@auth.route("/logout")
def logout():
    session.clear()
    return redirect("/")


def get_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
<<<<<<< Updated upstream
        cursor.execute("""
            SELECT id, username, password, role
=======
        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                password,
                role,
                status
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
            FROM users
            WHERE username = ? AND password = ?
        """, (username, password))

        user = cursor.fetchone()
<<<<<<< Updated upstream
=======

        if not user:
            return None

        if not verify_password(
            user["password"],
            password
        ):
            return None


        if user["status"] == "inactive":

            return "inactive"

<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
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
        username = request.form["username"]
        password = request.form["password"]

        user = get_user(
        username,
        password
    )


        if user == "inactive":

            session["login_error"] = (
                "Your account has been deactivated. Please contact the administrator."
            )

            session["login_username"] = username

            return redirect(
                url_for("auth.login")
            )


        if user:
            role = user[3]

            session["user_id"] = user[0]
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
<<<<<<< Updated upstream
<<<<<<< Updated upstream
        username = request.form["username"]
=======
=======
>>>>>>> Stashed changes

        username = request.form["username"].strip()

        email = (
            request.form["email"]
            .strip()
            .lower()
        )

>>>>>>> Stashed changes
        password = request.form["password"]

        confirm_password = request.form["confirm_password"]
        
        account_type = request.form["account_type"]

        if account_type not in ("student", "supervisor"):

            flash(
                "Invalid account type.",
                "danger"
            )

            return render_template(
                "auth/signup.html"
            )
        
        
        # Password confirmation
        if password != confirm_password:

<<<<<<< Updated upstream
<<<<<<< Updated upstream
        # Validate password length
        if len(password) < 6:
            return "Password must be at least 6 characters ❌"
=======
=======
>>>>>>> Stashed changes
            flash(
                "Passwords do not match ❌",
                "danger"
            )

            return render_template(
                "auth/signup.html"
            )


        # Password length
        if len(password) < 8:

            flash(
                "Password must be at least 8 characters ❌",
                "danger"
            )

            return render_template(
                "auth/signup.html"
            )

<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes

        conn = get_db_connection()
        cursor = conn.cursor()


        try:
<<<<<<< Updated upstream
<<<<<<< Updated upstream
            # Check if username already exists
            cursor.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,)
            )

            if cursor.fetchone():
                return "Username already exists ❌"

            # New accounts remain pending exactly as before
            cursor.execute("""
                INSERT INTO users (username, password, role)
                VALUES (?, ?, 'pending')
            """, (username, password))
=======
=======
>>>>>>> Stashed changes

            # Duplicate username/email check
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE username = ?
                OR LOWER(email) = LOWER(?)
                """,
                (
                    username,
                    email
                )
            )


            existing_user = cursor.fetchone()


            if existing_user:

                flash(
                    "Username or email already exists ❌",
                    "danger"
                )

                return render_template(
                    "auth/signup.html"
                )


            password_hash = hash_password(password)
            
            pending_role = (
                "pending_student"
                if account_type == "student"
                else "pending_supervisor"
            )

            cursor.execute(
                """
                INSERT INTO users
                (
                    username,
                    email,
                    password,
                    role
                )

                VALUES
                (?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    password_hash,
                    pending_role
                )
            )
>>>>>>> Stashed changes


            user_id = cursor.lastrowid


            if account_type == "student":

                cursor.execute(
                    """
                    INSERT INTO student_profiles
                    (
                        user_id,
                        profile_completed
                    )

                    VALUES
                    (?,0)
                    """,
                    (
                        user_id,
                    )
                )



            user_id = cursor.lastrowid


            if account_type == "student":

                cursor.execute(
                    """
                    INSERT INTO student_profiles
                    (
                        user_id,
                        profile_completed
                    )

                    VALUES
                    (?,0)
                    """,
                    (
                        user_id,
                    )
                )


            conn.commit()


        finally:

            cursor.close()
            conn.close()



        flash(
            "Account created successfully. Wait for approval.",
            "success"
        )

        return redirect(
            url_for("auth.login")
        )


    return render_template(
        "auth/signup.html"
    )
