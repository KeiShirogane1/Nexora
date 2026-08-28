from flask import Blueprint, current_app, render_template, request, redirect, session, send_file, flash
from routes.security import role_required
from database.db import get_db_connection

from services.profile_service import (
    update_student_profile,
    get_student_profile_data
)

import os
from werkzeug.utils import secure_filename
from datetime import datetime

<<<<<<< Updated upstream
<<<<<<< Updated upstream
=======
=======
>>>>>>> Stashed changes
def get_student_profile():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            first_name,
            middle_name,
            last_name,
            age,
            student_id,
            profile_picture,
            phone_number,
            home_address,
            grade_year,
            major_program

        FROM student_profiles

        WHERE user_id = ?

    """,
    (
        session["user_id"],
    ))

    profile = cursor.fetchone()

    conn.close()

    return profile


def format_title_case(value):

    lowercase_words = {
        "of",
        "in",
        "and",
        "for",
        "to"
    }

    words = value.lower().split()

    formatted = []

    for word in words:

        if word in lowercase_words:
            formatted.append(word)

        else:
            formatted.append(
                word.capitalize()
            )

    return " ".join(formatted)


def parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value

    return datetime.fromisoformat(value)


>>>>>>> Stashed changes
def format_time(timestamp):
    if not timestamp:
        return None

    return datetime.fromisoformat(timestamp).strftime("%I:%M %p").lstrip("0")

student = Blueprint("student", __name__)

@student.route("/student/dashboard")
@role_required("student")
def student_dashboard():

    conn = get_db_connection()
    cursor = conn.cursor()
    
    student_user_id = int(session["user_id"])

    # =========================
    # STUDENT PROFILE
    # =========================

    cursor.execute("""
        SELECT
            first_name,
            middle_name,
            last_name,
            age,
            student_id,
            profile_picture,
            phone_number,
            home_address,
            grade_year,
            major_program

        FROM student_profiles

        WHERE user_id = ?

    """,
    (
        session["user_id"],
    ))


    profile = cursor.fetchone()

   # ==============================
    # GET STUDENT INTERNSHIP
    # ==============================

    cursor.execute("""
        SELECT
            i.company_name,
            i.position,
            i.supervisor_name,
            i.start_date,
            i.end_date,
            i.required_hours,
            i.completed_hours,
            i.status

        FROM internships i

        JOIN users u
        ON i.student_id = u.id

        WHERE u.id = ?

    """,
    (
        session["user_id"],
    ))


    internship = cursor.fetchone()

    if not profile or profile[8] is None:

        conn.close()

        return redirect(
            "/student/profile/setup"
        )



    # =========================
    # DASHBOARD STATISTICS
    # =========================


    # Total logs

    cursor.execute("""
        SELECT COUNT(*)
        FROM logs
        WHERE student_id = ?
    """,
    (
        session["user_id"],
    ))

    log_count = cursor.fetchone()[0]



    # Total tasks

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE student_id = ?
    """,
    (
        session["user_id"],
    ))

    task_total = cursor.fetchone()[0]



    # Completed tasks

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE student_id = ?
        AND status = 'Submitted'
    """,
    (
        session["user_id"],
    ))

    task_completed = cursor.fetchone()[0]



    # Documents

    cursor.execute("""
        SELECT COUNT(*)
        FROM documents
        WHERE student_id = ?
    """,
    (
        session["user_id"],
    ))

    document_count = cursor.fetchone()[0]



    # Attendance

    cursor.execute("""
        SELECT COUNT(*)
        FROM attendance
        WHERE student_id = ?
    """,
    (
        session["user_id"],
    ))

    attendance_count = cursor.fetchone()[0]



    conn.close()


    # ==========================
    # RECENT ACTIVITY
    # ==========================


    conn = get_db_connection()
    cursor = conn.cursor()



    recent_logs = cursor.execute(
        """
        SELECT *
        FROM logs
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            session["user_id"],
        )
    ).fetchall()



    recent_tasks = cursor.execute(
        """
        SELECT *
        FROM tasks
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            session["user_id"],
        )
    ).fetchall()



    recent_documents = cursor.execute(
        """
        SELECT *
        FROM documents
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            session["user_id"],
        )
    ).fetchall()



    recent_attendance = cursor.execute(
        """
        SELECT *
        FROM attendance
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            session["user_id"],
        )
    ).fetchall()



    conn.close()



    return render_template(
        "student/dashboard.html",

        profile=profile,
        
        internship=internship,

        log_count=log_count,

        task_total=task_total,

        task_completed=task_completed,

        document_count=document_count,

        attendance_count=attendance_count,

        recent_logs=recent_logs,

        recent_tasks=recent_tasks,

        recent_documents=recent_documents,

        recent_attendance=recent_attendance
    )

@student.route("/student/clock-in", methods=["POST"])
@role_required("student")
def clock_in():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the student already has an open attendance session
    cursor.execute("""
        SELECT id
        FROM attendance
        WHERE student_id = ?
        AND status = 'Open'
    """, (session["user_id"],))

    existing_session = cursor.fetchone()

    if existing_session:
        conn.close()
        return redirect("/student/logbook")

    # Create a new attendance session

    clock_in = datetime.now()
    cursor.execute("""
        INSERT INTO attendance (
            student_id,
            clock_in,
            status
        )
        VALUES (
            ?,
            ?,
            ?
        )
    """, (session["user_id"], clock_in, "Open"))

    conn.commit()
    conn.close()

    return redirect("/student/logbook")

@student.route("/student/logbook")
@role_required("student")
def logbook():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Current attendance session
    cursor.execute("""
        SELECT
            id,
            clock_in,
            clock_out,
            hours_rendered,
            status
        FROM attendance
        WHERE student_id = ?
        AND status = 'Open'
    """, (session["user_id"],))

    attendance = cursor.fetchone()

    logs = []

    attendance = (
    attendance[0],
    format_time(attendance[1]),
    format_time(attendance[2]),
    attendance[3],
    attendance[4]
    ) if attendance else None

    # Load logs only if an open session exists
    if attendance:

        cursor.execute("""
            SELECT id, content, created_at
            FROM logs
            WHERE attendance_id = ?
            ORDER BY created_at DESC
        """, (attendance[0],))

        logs = cursor.fetchall()

        logs = [
            (
                log[0],
                log[1],
                format_time(log[2])
            )
            for log in logs
        ]

    # Attendance history
    cursor.execute("""
        SELECT id, clock_in, clock_out, hours_rendered, status
        FROM attendance
        WHERE student_id = ?
        ORDER BY clock_in DESC
    """, (session["user_id"],))

    history = cursor.fetchall()

    history = [
        (
            record[0],
            format_time(record[1]),
            format_time(record[2]),
            record[3],
            record[4]
        )
        for record in history
    ]

    conn.close()

    return render_template(
        "student/logbook.html",
        attendance=attendance,
        logs=logs,
        history=history,
        profile=get_student_profile(),
        active_page="logbook"
    )

@student.route("/student/clock-out", methods=["POST"])
@role_required("student")
def clock_out():

    conn = get_db_connection()
    cursor = conn.cursor()

    # Find the student's current open attendance
    cursor.execute("""
        SELECT
            id,
            clock_in
        FROM attendance
        WHERE student_id = ?
        AND status = 'Open'
    """, (session["user_id"],))

    attendance = cursor.fetchone()

    if not attendance:
        conn.close()
        return redirect("/student/logbook")

    attendance_id = attendance[0]
    clock_in = datetime.fromisoformat(attendance[1])

    current_time = datetime.now()

    hours_rendered = max(
        0,
        round(
        (current_time - clock_in).total_seconds() / 3600,
        2
    )
    )

    cursor.execute("""
        UPDATE attendance
        SET clock_out = ?, hours_rendered = ?, status = 'Completed'
        WHERE id = ?
    """, (
        current_time,
        hours_rendered,
        attendance_id
    ))

    conn.commit()
    conn.close()

    return redirect("/student/logbook")

@student.route("/student/log/add", methods=["POST"])
@role_required("student")
def add_log():

    conn = get_db_connection()
    cursor = conn.cursor()

    content = request.form["content"].strip()

    if not content:
        conn.close()
        return redirect("/student/logbook")

    # Find the student's current open attendance session
    cursor.execute("""
        SELECT id
        FROM attendance
        WHERE student_id = ?
        AND status = 'Open'
    """, (session["user_id"],))

    attendance = cursor.fetchone()

    if not attendance:
        conn.close()
        return redirect("/student/logbook")

    attendance_id = attendance[0]

    # Insert log entry
    current_time = datetime.now()

    cursor.execute("""
        INSERT INTO logs (
            attendance_id,
            student_id,
            content,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        attendance_id,
        session["user_id"],
        content,
        current_time
    ))

    conn.commit()
    conn.close()

    return redirect("/student/logbook")

@student.route("/student/log/<int:log_id>/edit", methods=["GET", "POST"])
@role_required("student")
def edit_log(log_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            logs.id,
            logs.content,
            attendance.status
        FROM logs
        JOIN attendance
            ON logs.attendance_id = attendance.id
        WHERE logs.id = ?
        AND logs.student_id = ?
    """, (log_id, session["user_id"]))

    log = cursor.fetchone()

    if not log:
        conn.close()
        return "Log not found.", 404

    # Prevent editing after clock out
    if log[2] != "Open":
        conn.close()
        return redirect("/student/logbook")

    if request.method == "POST":

        content = request.form["content"].strip()

        if content:

            cursor.execute("""
                UPDATE logs
                SET content = ?
                WHERE id = ?
            """, (
                content,
                log_id
            ))

            conn.commit()

        conn.close()

        return redirect("/student/logbook")

    conn.close()

    return render_template(
        "student/edit_log.html",
        log=log,
        active_page="logbook"
    )

@student.route("/student/log/<int:log_id>/delete", methods=["POST"])
@role_required("student")
def delete_log(log_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify ownership and that the session is still open
    cursor.execute("""
        SELECT
            logs.id,
            attendance.status
        FROM logs
        JOIN attendance
            ON logs.attendance_id = attendance.id
        WHERE logs.id = ?
        AND logs.student_id = ?
    """, (log_id, session["user_id"]))

    log = cursor.fetchone()

    if not log:
        conn.close()
        return "Log not found.", 404

    if log[1] != "Open":
        conn.close()
        return redirect("/student/logbook")

    cursor.execute("""
        DELETE FROM logs
        WHERE id = ?
    """, (log_id,))

    conn.commit()
    conn.close()

    return redirect("/student/logbook")

@student.route("/student/session/<int:attendance_id>")
@role_required("student")
def view_session(attendance_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Retrieve the attendance session
    cursor.execute("""
        SELECT
            id,
            clock_in,
            clock_out,
            hours_rendered,
            status
        FROM attendance
        WHERE id = ?
        AND student_id = ?
    """, (
        attendance_id,
        session["user_id"]
    ))

    attendance = cursor.fetchone()

    if not attendance:
        conn.close()
        return "Session not found.", 404

    # Retrieve all logs belonging to this attendance session
    cursor.execute("""
        SELECT id, content, created_at
        FROM logs
        WHERE attendance_id = ?
        ORDER BY created_at ASC
    """, (attendance_id,))

    logs = cursor.fetchall()

    attendance = list(attendance)

    attendance[1] = datetime.fromisoformat(attendance[1]).strftime("%I:%M %p")

    if attendance[2]:
        attendance[2] = datetime.fromisoformat(attendance[2]).strftime("%I:%M %p")
    
    logs = [
        (
            log[0],
            log[1],
            datetime.fromisoformat(log[2]).strftime("%I:%M %p")
        )
        for log in logs
    ]

    conn.close()

    return render_template(
        "student/session_details.html",
        attendance=attendance,
        logs=logs,
        active_page="logbook"
    )

@student.route('/student/tasks')
@role_required("student")
def tasks():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, task_title, assigned_at, deadline, status
        FROM tasks
        WHERE student_id = ?
        ORDER BY assigned_at DESC
    """, (session["user_id"],))

    tasks = cursor.fetchall()

    conn.close()

    return render_template(
        "student/tasks.html",
        tasks=tasks,
        active_page="tasks"
    )

@student.route("/student/task/<int:task_id>")
@role_required("student")
def task_details(task_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            task_title,
            task_description,
            assigned_at,
            deadline,
            status,
            requires_submission,
            allow_late_submission
        FROM tasks
        WHERE id = ?
        AND student_id = ?
    """, (task_id, session["user_id"]))

    task = cursor.fetchone()

    if not task:
        conn.close()
        return "Task not found.", 404

    cursor.execute("""
        SELECT id, filename, submitted_at
        FROM task_submissions
        WHERE task_id = ?
        ORDER BY submitted_at DESC
        """, (task_id,))

    uploads = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            filename,
            submitted_at,
            remarks
        FROM task_submissions
        WHERE task_id = ?
    """, (task_id,))

    submission = cursor.fetchone()

    conn.close()

    return render_template(
        "student/task_details.html",
        task=task,
        submission=submission,
        uploads=uploads,
        task_id=task_id,
        active_page="tasks"
    )

@student.route("/student/task/<int:task_id>/upload", methods=["POST"])
@role_required("student")
def task_upload(task_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    file = request.files.get("file")

    if file and file.filename:

        filename = secure_filename(file.filename)

        filepath = os.path.join(
            current_app.config["UPLOAD_FOLDER"],
            filename
        )

        file.save(filepath)

        # Remove previous submission (one upload only)
        cursor.execute("""
            DELETE FROM task_submissions
            WHERE task_id = ?
        """, (task_id,))

        cursor.execute("""
            INSERT INTO task_submissions
            (task_id, filename, filepath)
            VALUES (?, ?, ?)
        """, (
            task_id,
            filename,
            filepath
        ))

        conn.commit()

    conn.close()

    return redirect(f"/student/task/{task_id}")

@student.route("/student/task/submission/<int:submission_id>")
@role_required("student")
def view_task_submission(submission_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ts.filename,
            ts.filepath
        FROM task_submissions ts
        JOIN tasks t
            ON ts.task_id = t.id
        WHERE ts.id = ?
        AND t.student_id = ?
    """, (submission_id, session["user_id"]))

    submission = cursor.fetchone()

    conn.close()

    if not submission:
        return "Submission not found.", 404

    return send_file(
        submission[1],
        as_attachment=False
    )

@student.route("/student/task/submission/<int:submission_id>/delete")
@role_required("student")
def delete_task_submission(submission_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ts.task_id,
            ts.filepath
        FROM task_submissions ts
        JOIN tasks t
            ON ts.task_id = t.id
        WHERE ts.id = ?
        AND t.student_id = ?
    """, (submission_id, session["user_id"]))

    submission = cursor.fetchone()

    if not submission:
        conn.close()
        return "Submission not found.", 404

    task_id = submission[0]
    filepath = submission[1]

    if os.path.exists(filepath):
        os.remove(filepath)

    cursor.execute("""
        DELETE FROM task_submissions
        WHERE id = ?
    """, (submission_id,))

    conn.commit()
    conn.close()

    return redirect(f"/student/task/{task_id}")

@student.route("/student/task/<int:task_id>/submit", methods=["POST"])
@role_required("student")
def submit_task(task_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify the task belongs to the logged-in student
    cursor.execute("""
        SELECT id
        FROM tasks
        WHERE id = ?
        AND student_id = ?
    """, (task_id, session["user_id"]))

    task = cursor.fetchone()

    if not task:
        conn.close()
        return "Task not found.", 404

    # Mark task as submitted
    cursor.execute("""
        UPDATE tasks
        SET status = 'Submitted'
        WHERE id = ?
    """, (task_id,))

    conn.commit()
    conn.close()

    return redirect(f"/student/task/{task_id}")

#documents

@student.route('/student/documents', methods=['GET', 'POST'])
@role_required("student")
def documents():
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        file = request.files['file']

        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(
                current_app.config['UPLOAD_FOLDER'],
                filename
                )
            file.save(filepath)

            cursor.execute(
                "INSERT INTO documents (student_id, filename, filepath) VALUES (?, ?, ?)",
                (session['user_id'], filename, filepath)
            )
            conn.commit()

    cursor.execute(
        """
        SELECT id, filename, uploaded_at
        FROM documents
        WHERE student_id = ?
        ORDER BY uploaded_at DESC
        """,
        (session['user_id'],)
    )
    docs = cursor.fetchall()
    conn.close()

    return render_template('student/documents.html', docs=docs, active_page="documents")

@student.route("/student/document/<int:document_id>")
@role_required("student")
def view_document(document_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT filename, filepath
        FROM documents
        WHERE id = ?
        AND student_id = ?
    """, (document_id, session["user_id"]))

    document = cursor.fetchone()

    conn.close()

    if not document:
        return "Document not found.", 404

    return send_file(
        document[1],
        as_attachment=False
    )

@student.route(
    "/student/profile/setup",
    methods=["GET", "POST"]
)
@role_required("student")
def profile_setup():

    conn = get_db_connection()
    cursor = conn.cursor()


    if request.method == "POST":


        first_name = request.form["first_name"]
        middle_name = request.form["middle_name"]
        last_name = request.form["last_name"]

        age = request.form["age"]

        student_id = request.form["student_id"]

        phone_number = request.form["phone_number"]

        home_address = request.form["home_address"]

        grade_year = request.form["grade_year"]

        major_program = request.form["major_program"]



        # ==========================
        # PROFILE PICTURE
        # ==========================

        profile_picture = None


        cropped_image = request.form.get(
            "cropped_image"
        )


        if cropped_image:


            import base64


            image_data = cropped_image.split(",")[1]


            filename = (
                str(session["user_id"])
                +
                "_profile.jpg"
            )


            filepath = os.path.join(
                current_app.config["PROFILE_UPLOAD_FOLDER"],
                filename
            )


            with open(filepath, "wb") as file:

                file.write(
                    base64.b64decode(image_data)
                )


            profile_picture = filename



        # ==========================
        # UPDATE PROFILE
        # ==========================


        cursor.execute(
            """
            UPDATE student_profiles

            SET

            first_name = ?,
            middle_name = ?,
            last_name = ?,
            age = ?,
            student_id = ?,
            profile_picture = ?,
            phone_number = ?,
            home_address = ?,
            grade_year = ?,
            major_program = ?,
            profile_completed = 1


            WHERE user_id = ?

            """,
            (

                first_name,
                middle_name,
                last_name,

                age,

                student_id,

                profile_picture,

                phone_number,

                home_address,

                grade_year,

                major_program,

                session["user_id"]

            )
        )


        conn.commit()

        conn.close()


        flash(
            "Profile completed successfully!",
            "success"
        )


        return redirect(
            "/student/dashboard"
        )



    conn.close()


    return render_template(
        "student/profile_setup.html"
    )


@student.route("/student/profile")
@role_required("student")
def student_profile():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
        first_name,
        middle_name,
        last_name,
        age,
        student_id,
        profile_picture,
        phone_number,
        home_address,
        grade_year,
        major_program,
        emergency_name,
        emergency_relationship,
        emergency_phone,
        emergency_email,
        users.email

    FROM student_profiles

    JOIN users
    ON student_profiles.user_id = users.id

    WHERE student_profiles.user_id = ?

    """,
    (
        session["user_id"],
    ))

    profile = cursor.fetchone()
    
        # ==========================
    # PROFILE COMPLETION
    # ==========================

    fields = [

        profile[0],
        profile[1],
        profile[2],
        profile[3],
        profile[4],
        profile[5],
        profile[6],
        profile[7],
        profile[8],
        profile[9],
        profile[10],
        profile[11],
        profile[12]

    ]


    completed = sum(
        1 for field in fields
        if field
    )


    profile_percentage = int(
        (completed / len(fields)) * 100
    )

    conn.close()

    return render_template(
        "student/profile.html",
        profile=profile,
        profile_percentage=profile_percentage,
        active_page="profile"
    )
    
@student.route(
    "/student/profile/edit",
    methods=["GET", "POST"]
)
@role_required("student")
def edit_profile():


    if request.method == "POST":


        profile_data = get_student_profile_data(
            request.form
        )


        # ==========================
        # PROFILE VALIDATION
        # ==========================


        age = profile_data.get("age")


        if age:

            try:

                age = int(age)

                if age < 15 or age > 100:

                    flash(
                        "Invalid age entered.",
                        "error"
                    )

                    return redirect(
                        "/student/profile/edit"
                    )


                profile_data["age"] = age


            except ValueError:

                flash(
                    "Age must be a number.",
                    "error"
                )

                return redirect(
                    "/student/profile/edit"
                )



        # Student cannot change Student ID

        conn = get_db_connection()

        cursor = conn.cursor()


        cursor.execute(
            """
            SELECT student_id
            FROM student_profiles
            WHERE user_id = ?
            """,
            (
                session["user_id"],
            )
        )


        current_student_id = cursor.fetchone()[0]


        conn.close()



        profile_data["student_id"] = current_student_id


        profile_data["grade_year"] = format_title_case(
            profile_data["grade_year"]
        )


        profile_data["major_program"] = format_title_case(
            profile_data["major_program"]
        )
        
        errors = {}


        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        middle_name = request.form.get("middle_name")
        age = request.form.get("age")
        phone = request.form.get("phone_number")
        student_id = request.form.get("student_id")


        # REQUIRED CHECK

        if not first_name:
            errors["first_name"] = "First name is required."

        elif not first_name.replace(" ", "").isalpha():
            errors["first_name"] = "First name must contain letters only."


        if not last_name:
            errors["last_name"] = "Last name is required."

        elif not last_name.replace(" ", "").isalpha():
            errors["last_name"] = "Last name must contain letters only."
            
        if middle_name:

            if not middle_name.replace(" ", "").isalpha():

                errors["middle_name"] = "Middle name must contain letters only."


        if not student_id:
            errors["student_id"] = "Student ID is required."



        # AGE CHECK

        if age:

            try:

                age_number = int(age)

                if age_number < 15 or age_number > 100:
                    errors["age"] = "Age must be between 15 and 100."

            except:

                errors["age"] = "Age must be a valid number."



        # PHONE CHECK

        if phone:

            if not phone.isdigit():

                errors["phone_number"] = "Phone number must contain numbers only."



        # STOP SAVE IF ERRORS

        if errors:

            flash(
                "Please fix the highlighted fields.",
                "error"
            )


            student = {
                "first_name": request.form.get("first_name"),
                "middle_name": request.form.get("middle_name"),
                "last_name": request.form.get("last_name"),
                "age": request.form.get("age"),
                "student_id": request.form.get("student_id"),
                "phone_number": request.form.get("phone_number"),
                "home_address": request.form.get("home_address"),
                "grade_year": request.form.get("grade_year"),
                "major_program": request.form.get("major_program"),
                "emergency_name": request.form.get("emergency_name"),
                "emergency_relationship": request.form.get("emergency_relationship"),
                "emergency_phone": request.form.get("emergency_phone"),
                "emergency_email": request.form.get("emergency_email"),
                "email": session.get("email", "")
            }


        return render_template(
            "student/profile_edit.html",
            student=student,
            errors=errors
        )

        update_student_profile(
            session["user_id"],
            profile_data
        )


        flash(
            "Profile updated successfully!",
            "success"
        )


        return redirect(
            "/student/profile"
        )

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            first_name,
            middle_name,
            last_name,
            age,
            student_id,
            profile_picture,
            phone_number,
            home_address,
            grade_year,
            major_program,
            emergency_name,
            emergency_relationship,
            emergency_phone,
            emergency_email

        FROM student_profiles

        WHERE user_id = ?

    """,
    (
        session["user_id"],
    ))


    profile = cursor.fetchone()

    if not profile:
        conn.close()
        flash("Please complete your profile setup first.", "warning")
        return redirect("/student/profile/setup")

    cursor.execute("""
        SELECT email
        FROM users
        WHERE id = ?
    """, (session["user_id"],))

    user_email = cursor.fetchone()[0]


    student = {
        "id": session["user_id"],
        "first_name": profile[0],
        "middle_name": profile[1],
        "last_name": profile[2],
        "age": profile[3],
        "student_id": profile[4],
        "profile_picture": profile[5],
        "phone_number": profile[6],
        "home_address": profile[7],
        "grade_year": profile[8],
        "major_program": profile[9],
        "emergency_name": profile[10],
        "emergency_relationship": profile[11],
        "emergency_phone": profile[12],
        "emergency_email": profile[13],
        "email": user_email
    }


    return render_template(
        "student/profile_edit.html",
        student=student
    )
    
    
    
@student.route(
    "/student/profile/photo",
    methods=["POST"]
)
@role_required("student")
def update_profile_photo():

    file = request.files.get(
        "profile_picture"
    )


    if not file:
        return "No image received", 400


    filename = (
        str(session["user_id"])
        +
        "_profile.jpg"
    )


    filepath = os.path.join(
        current_app.config["PROFILE_UPLOAD_FOLDER"],
        filename
    )


    file.save(filepath)


    conn = get_db_connection()
    cursor = conn.cursor()


    cursor.execute(
        """
        UPDATE student_profiles
        SET profile_picture = ?
        WHERE user_id = ?
        """,
        (
            filename,
            session["user_id"]
        )
    )


    conn.commit()
    conn.close()


    return "OK"