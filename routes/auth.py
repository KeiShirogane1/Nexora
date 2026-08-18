from flask import Blueprint, render_template, request, redirect, url_for, session
import sqlite3

auth = Blueprint("auth", __name__)

@auth.route("/logout")
def logout():
    session.clear()
    return redirect("/")

def get_user(username, password):
    conn = sqlite3.connect("nexora.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM users 
        WHERE username = ? AND password = ?
    """, (username, password))

    user = cursor.fetchone()
    conn.close()
    return user

@auth.route("/")
def welcome():
    return render_template("welcome.html")

@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = get_user(username, password)

        if user:
            role = user[3]  # (id, username, password, role)

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
        username = request.form["username"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        # Validate passwords match
        if password != confirm_password:
            return "Passwords do not match ❌"

        # Validate password length
        if len(password) < 6:
            return "Password must be at least 6 characters ❌"

        conn = sqlite3.connect("nexora.db")
        cursor = conn.cursor()

        # Check if username already exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            return "Username already exists ❌"

        cursor.execute("""
            INSERT INTO users (username, password, role)
            VALUES (?, ?, 'pending')
        """, (username, password))

        conn.commit()
        conn.close()

        return redirect("/login")

    return render_template("auth/signup.html")