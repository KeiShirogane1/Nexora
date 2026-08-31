"""Nexora Classroom controller.

A lightweight Google-Classroom-style layer built on top of Nexora's existing
internship workflows. Access is always scoped to the logged-in user.
"""
import secrets
import string
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection


classroom = Blueprint("classroom", __name__)


def _class_code(conn):
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = "NXR-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not conn.execute("SELECT 1 FROM classrooms WHERE code = ?", (code,)).fetchone():
            return code
    raise RuntimeError("Unable to generate a unique classroom code")


def _get_class(conn, classroom_id):
    return conn.execute(
        """SELECT c.id, c.name, c.section, c.description, c.code, c.archived,
                  c.supervisor_id, u.username AS supervisor_name
           FROM classrooms c
           JOIN users u ON u.id = c.supervisor_id
           WHERE c.id = ?""",
        (classroom_id,),
    ).fetchone()


def _supervisor_owns(conn, classroom_id):
    return conn.execute(
        "SELECT 1 FROM classrooms WHERE id = ? AND supervisor_id = ?",
        (classroom_id, session["user_id"]),
    ).fetchone() is not None


def _student_member(conn, classroom_id):
    return conn.execute(
        "SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ?",
        (classroom_id, session["user_id"]),
    ).fetchone() is not None


# ---------------- SUPERVISOR: MY CLASSES ----------------
@classmethod.route("/supervisor/classes") if False else classroom.route("/supervisor/classes")
@role_required("supervisor")
def supervisor_classes():
    conn = get_db_connection()
    classes = conn.execute(
        """SELECT c.id, c.name, c.section, c.description, c.code, c.archived,
                  COUNT(cs.id) AS student_count
           FROM classrooms c
           LEFT JOIN classroom_students cs ON cs.classroom_id = c.id
           WHERE c.supervisor_id = ?
           GROUP BY c.id, c.name, c.section, c.description, c.code, c.archived
           ORDER BY c.archived ASC, c.created_at DESC""",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return render_template("classroom/supervisor_classes.html", classes=classes, active_page="classes")


@classroom.route("/supervisor/classes/create", methods=["GET", "POST"])
@role_required("supervisor")
def create_class():
    if request.method == "GET":
        return render_template("classroom/create_class.html", active_page="classes")

    name = (request.form.get("name") or "").strip()
    section = (request.form.get("section") or "").strip()
    description = (request.form.get("description") or "").strip()

    if len(name) < 2 or len(name) > 120:
        flash("Class name must be 2-120 characters.", "danger")
        return redirect("/supervisor/classes/create")
    if len(section) > 80 or len(description) > 1000:
        flash("Section or description is too long.", "danger")
        return redirect("/supervisor/classes/create")

    conn = get_db_connection()
    code = _class_code(conn)
    conn.execute(
        """INSERT INTO classrooms (supervisor_id, name, section, description, code)
           VALUES (?, ?, ?, ?, ?)""",
        (session["user_id"], name, section or None, description or None, code),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM classrooms WHERE code = ?", (code,)).fetchone()
    conn.close()
    flash(f"Class created. Share code {code} with your students.", "success")
    return redirect(f"/supervisor/classes/{row[0]}")


@classroom.route("/supervisor/classes/<int:classroom_id>")
@role_required("supervisor")
def supervisor_classroom(classroom_id):
    conn = get_db_connection()
    if not _supervisor_owns(conn, classroom_id):
        conn.close()
        return "Classroom not found or access denied", 404
    course = _get_class(conn, classroom_id)
    students = conn.execute(
        """SELECT u.id, u.username, u.email, cs.joined_at
           FROM classroom_students cs
           JOIN users u ON u.id = cs.student_id
           WHERE cs.classroom_id = ?
           ORDER BY u.username""",
        (classroom_id,),
    ).fetchall()
    posts = conn.execute(
        """SELECT id, title, body, post_type, created_at
           FROM classroom_posts WHERE classroom_id = ?
           ORDER BY created_at DESC LIMIT 20""",
        (classroom_id,),
    ).fetchall()
    assignments = conn.execute(
        """SELECT a.id, a.title, a.description, a.due_at, a.points,
                  COUNT(s.id) AS submission_count
           FROM classroom_assignments a
           LEFT JOIN classroom_submissions s ON s.assignment_id = a.id
           WHERE a.classroom_id = ?
           GROUP BY a.id, a.title, a.description, a.due_at, a.points
           ORDER BY a.due_at IS NULL, a.due_at ASC, a.created_at DESC""",
        (classroom_id,),
    ).fetchall()
    conn.close()
    return render_template(
        "classroom/supervisor_class.html",
        course=course, students=students, posts=posts, assignments=assignments,
        active_page="classes",
    )


@classroom.route("/supervisor/classes/<int:classroom_id>/post", methods=["POST"])
@role_required("supervisor")
def create_post(classroom_id):
    conn = get_db_connection()
    if not _supervisor_owns(conn, classroom_id):
        conn.close()
        return "Classroom not found or access denied", 404
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not body or len(body) > 5000 or len(title) > 160:
        flash("Post content is required and must be within the allowed length.", "danger")
        conn.close()
        return redirect(f"/supervisor/classes/{classroom_id}")
    conn.execute(
        "INSERT INTO classroom_posts (classroom_id, author_id, title, body) VALUES (?, ?, ?, ?)",
        (classroom_id, session["user_id"], title or None, body),
    )
    conn.commit()
    conn.close()
    flash("Announcement posted.", "success")
    return redirect(f"/supervisor/classes/{classroom_id}")


@classroom.route("/supervisor/classes/<int:classroom_id>/assignment", methods=["POST"])
@role_required("supervisor")
def create_assignment(classroom_id):
    conn = get_db_connection()
    if not _supervisor_owns(conn, classroom_id):
        conn.close()
        return "Classroom not found or access denied", 404
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    due_raw = (request.form.get("due_at") or "").strip()
    points_raw = (request.form.get("points") or "100").strip()
    if len(title) < 2 or len(title) > 160 or len(description) > 5000:
        flash("Assignment title/description is invalid.", "danger")
        conn.close()
        return redirect(f"/supervisor/classes/{classroom_id}")
    due_at = None
    if due_raw:
        try:
            due_at = datetime.fromisoformat(due_raw.replace("T", " "))
        except ValueError:
            flash("Invalid due date.", "danger")
            conn.close()
            return redirect(f"/supervisor/classes/{classroom_id}")
    try:
        points = float(points_raw)
        if points < 0 or points > 100000:
            raise ValueError
    except ValueError:
        flash("Points must be a valid non-negative number.", "danger")
        conn.close()
        return redirect(f"/supervisor/classes/{classroom_id}")
    conn.execute(
        """INSERT INTO classroom_assignments
           (classroom_id, author_id, title, description, due_at, points)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (classroom_id, session["user_id"], title, description or None, due_at, points),
    )
    conn.commit()
    conn.close()
    flash("Assignment published.", "success")
    return redirect(f"/supervisor/classes/{classroom_id}")


@classroom.route("/supervisor/classes/<int:classroom_id>/archive", methods=["POST"])
@role_required("supervisor")
def archive_class(classroom_id):
    conn = get_db_connection()
    if not _supervisor_owns(conn, classroom_id):
        conn.close()
        return "Classroom not found or access denied", 404
    conn.execute(
        "UPDATE classrooms SET archived = CASE WHEN archived = 1 THEN 0 ELSE 1 END WHERE id = ?",
        (classroom_id,),
    )
    conn.commit()
    conn.close()
    flash("Classroom status updated.", "success")
    return redirect("/supervisor/classes")


# ---------------- STUDENT: JOIN + CLASS VIEW ----------------
@classroom.route("/student/classes")
@role_required("student")
def student_classes():
    conn = get_db_connection()
    classes = conn.execute(
        """SELECT c.id, c.name, c.section, c.description, c.code,
                  u.username AS supervisor_name
           FROM classroom_students cs
           JOIN classrooms c ON c.id = cs.classroom_id
           JOIN users u ON u.id = c.supervisor_id
           WHERE cs.student_id = ? AND c.archived = 0
           ORDER BY c.created_at DESC""",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return render_template("classroom/student_classes.html", classes=classes, active_page="classes")


@classroom.route("/student/classes/join", methods=["GET", "POST"])
@role_required("student")
def join_class():
    if request.method == "GET":
        return render_template("classroom/join_class.html", active_page="classes")
    code = (request.form.get("code") or "").strip().upper()
    conn = get_db_connection()
    course = conn.execute(
        "SELECT id, archived FROM classrooms WHERE code = ?", (code,)
    ).fetchone()
    if not course or course[1]:
        conn.close()
        flash("Class code is invalid or the class is archived.", "danger")
        return redirect("/student/classes/join")
    try:
        conn.execute(
            "INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)",
            (course[0], session["user_id"]),
        )
        conn.commit()
        flash("You joined the class successfully.", "success")
    except Exception:
        conn.rollback()
        flash("You are already a member of this class.", "info")
    conn.close()
    return redirect(f"/student/classes/{course[0]}")


@classroom.route("/student/classes/<int:classroom_id>")
@role_required("student")
def student_classroom(classroom_id):
    conn = get_db_connection()
    if not _student_member(conn, classroom_id):
        conn.close()
        return "Classroom not found or access denied", 404
    course = _get_class(conn, classroom_id)
    posts = conn.execute(
        "SELECT id, title, body, post_type, created_at FROM classroom_posts WHERE classroom_id = ? ORDER BY created_at DESC LIMIT 20",
        (classroom_id,),
    ).fetchall()
    assignments = conn.execute(
        """SELECT a.id, a.title, a.description, a.due_at, a.points,
                  s.status, s.grade, s.submitted_at
           FROM classroom_assignments a
           LEFT JOIN classroom_submissions s
             ON s.assignment_id = a.id AND s.student_id = ?
           WHERE a.classroom_id = ?
           ORDER BY a.due_at IS NULL, a.due_at ASC, a.created_at DESC""",
        (session["user_id"], classroom_id),
    ).fetchall()
    conn.close()
    return render_template(
        "classroom/student_class.html",
        course=course, posts=posts, assignments=assignments,
        active_page="classes",
    )
