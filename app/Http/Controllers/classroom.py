import os
import secrets
import string
import mimetypes
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, session, flash, url_for, current_app, send_file
from werkzeug.utils import secure_filename
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.notification_service import create_notification

ALLOWED_CLASSROOM_EXT = {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "txt", "zip", "png", "jpg", "jpeg", "gif"}
MAX_FILE_SIZE = 5 * 1024 * 1024

def _allowed_classroom_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_CLASSROOM_EXT

def _is_safe_path_classroom(base, target):
    try:
        base_abs = os.path.abspath(base)
        target_abs = os.path.abspath(target)
        return os.path.commonpath([base_abs]) == os.path.commonpath([base_abs, target_abs])
    except:
        return False

def _parse_due(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except:
            continue
    try:
        norm = value.replace("T", " ")
        return datetime.fromisoformat(norm)
    except:
        return None

classroom = Blueprint("classroom", __name__)

def _generate_code(cursor, attempts=10):
    for _ in range(attempts):
        rand = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        code = f"NXR-{rand}"
        cursor.execute("SELECT 1 FROM classrooms WHERE code = ?", (code,))
        if not cursor.fetchone():
            return code
    # fallback with longer
    return f"NXR-{secrets.token_hex(4).upper()}"

def _is_supervisor_owner(supervisor_id, classroom_id):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT supervisor_id FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
        if not row:
            return False
        sid = row["supervisor_id"] if "supervisor_id" in row.keys() else row[0]
        return int(sid) == int(supervisor_id)
    finally:
        conn.close()

def _is_student_member(student_id, classroom_id):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ?", (classroom_id, student_id)).fetchone()
        return row is not None
    finally:
        conn.close()

# Supervisor: My Intern Classrooms
@classroom.route("/supervisor/classes")
@role_required("supervisor")
def supervisor_classes():
    sid = session["user_id"]
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT c.id, c.name, c.section, c.description, c.code, c.archived, c.created_at,
                   (SELECT COUNT(*) FROM classroom_students cs WHERE cs.classroom_id = c.id) AS student_count,
                   u.username AS supervisor_name,
                   COALESCE(cid.company_name, '') AS company_name,
                   COALESCE(cid.work_arrangement, '') AS work_arrangement,
                   COALESCE(cid.location, '') AS location,
                   COALESCE(cid.hours_mode, 'not_specified') AS hours_mode,
                   COALESCE(cid.required_hours, 0) AS required_hours
            FROM classrooms c
            JOIN users u ON u.id = c.supervisor_id
            LEFT JOIN classroom_internship_details cid ON cid.classroom_id = c.id
            WHERE c.supervisor_id = ?
            ORDER BY c.created_at DESC
        """, (sid,)).fetchall()
        classes = []
        for r in rows:
            classes.append({
                "id": r["id"] if "id" in r.keys() else r[0],
                "name": r["name"] if "name" in r.keys() else r[1],
                "section": r["section"] if "section" in r.keys() else r[2],
                "description": r["description"] if "description" in r.keys() else r[3],
                "code": r["code"] if "code" in r.keys() else r[4],
                "archived": r["archived"] if "archived" in r.keys() else r[5],
                "status": "Archived" if (r["archived"] if "archived" in r.keys() else r[5]) else "Active",
                "student_count": r["student_count"] if "student_count" in r.keys() else r[7],
                "supervisor": r["supervisor_name"] if "supervisor_name" in r.keys() else r[8],
                "company_name": r["company_name"] if "company_name" in r.keys() else r[9],
                "work_arrangement": r["work_arrangement"] if "work_arrangement" in r.keys() else r[10],
                "location": r["location"] if "location" in r.keys() else r[11],
                "hours_mode": r["hours_mode"] if "hours_mode" in r.keys() else r[12],
                "required_hours": r["required_hours"] if "required_hours" in r.keys() else r[13],
            })
    finally:
        conn.close()
    return render_template("classroom/supervisor_classes.html", classes=classes, active_page="classes")

# Supervisor: Create Class
@classroom.route("/supervisor/classes/create", methods=["GET", "POST"])
@role_required("supervisor")
def create_class():
    if request.method == "POST":
        form_type = (request.form.get("form_type") or "classroom").strip().lower()

        if form_type == "internship":
            internship_title = (request.form.get("internship_title") or "").strip()
            company_name = (request.form.get("company_name") or "").strip()
            section = (request.form.get("internship_section") or "").strip()
            industry = (request.form.get("industry") or "").strip()
            work_arrangement = (request.form.get("work_arrangement") or "On-site").strip()
            compensation = (request.form.get("compensation") or "Unpaid").strip()
            location = (request.form.get("location") or "").strip()
            start_date = (request.form.get("start_date") or "").strip() or None
            end_date = (request.form.get("end_date") or "").strip() or None
            deadline = (request.form.get("deadline") or "").strip() or None
            required_hours_raw = (request.form.get("required_hours") or "").strip()
            company_website = (request.form.get("company_website") or "").strip()
            company_description = (request.form.get("company_description") or "").strip()
            internship_description = (request.form.get("internship_description") or "").strip()
            responsibilities = [
                item.strip() for item in request.form.getlist("responsibilities[]") if item.strip()
            ]
            qualifications = [
                item.strip() for item in request.form.getlist("qualifications[]") if item.strip()
            ]

            errors = {}
            if not internship_title or len(internship_title) < 3 or len(internship_title) > 150:
                errors["internship_title"] = "Internship title is required (3-150 chars)."
            if not company_name or len(company_name) < 2 or len(company_name) > 150:
                errors["company_name"] = "Company / organization is required (2-150 chars)."
            if not section or len(section) > 100:
                errors["internship_section"] = "Section is required (1-100 chars)."
            if len(industry) > 100:
                errors["industry"] = "Category / industry max 100 chars."
            if work_arrangement not in {"On-site", "Hybrid", "Remote"}:
                errors["work_arrangement"] = "Choose a valid work arrangement."
            if compensation not in {"Paid", "Unpaid"}:
                errors["compensation"] = "Choose a valid compensation option."
            if len(location) > 200:
                errors["location"] = "Location max 200 chars."

            for field_name, value in (("start_date", start_date), ("end_date", end_date), ("deadline", deadline)):
                if value:
                    try:
                        datetime.strptime(value, "%Y-%m-%d")
                    except ValueError:
                        errors[field_name] = "Enter a valid date."
            if start_date and end_date:
                try:
                    if datetime.strptime(end_date, "%Y-%m-%d") < datetime.strptime(start_date, "%Y-%m-%d"):
                        errors["end_date"] = "End date cannot be before the start date."
                except ValueError:
                    pass

            required_hours = None
            try:
                required_hours = int(required_hours_raw)
                if required_hours < 1 or required_hours > 10000:
                    raise ValueError()
            except (TypeError, ValueError):
                errors["required_hours"] = "Required hours must be between 1 and 10,000."

            if company_website:
                if len(company_website) > 500:
                    errors["company_website"] = "Company website max 500 chars."
                elif not company_website.lower().startswith(("http://", "https://")):
                    errors["company_website"] = "Company website must start with http:// or https://."
            if len(company_description) > 5000:
                errors["company_description"] = "Company description max 5000 chars."
            if not internship_description or len(internship_description) < 10 or len(internship_description) > 10000:
                errors["internship_description"] = "Internship description is required (10-10,000 chars)."
            if not responsibilities:
                errors["responsibilities"] = "Add at least one responsibility."
            elif len(responsibilities) > 20 or any(len(item) > 500 for item in responsibilities):
                errors["responsibilities"] = "Use up to 20 responsibilities, max 500 chars each."
            if not qualifications:
                errors["qualifications"] = "Add at least one qualification."
            elif len(qualifications) > 20 or any(len(item) > 500 for item in qualifications):
                errors["qualifications"] = "Use up to 20 qualifications, max 500 chars each."

            if errors:
                return render_template(
                    "classroom/create_class.html",
                    errors=errors,
                    form=request.form,
                    responsibilities=responsibilities or [""],
                    qualifications=qualifications or [""],
                    initial_view="internship",
                    active_page="classes",
                )

            conn = get_db_connection()
            cursor = None
            try:
                cursor = conn.cursor()
                code = _generate_code(cursor)
                parent_description = f"Internship classroom for {company_name}"
                cursor.execute("""
                    INSERT INTO classrooms
                    (supervisor_id, name, section, description, code, classroom_type, archived)
                    VALUES (?, ?, ?, ?, ?, 'internship', 0)
                """, (session["user_id"], internship_title, section, parent_description, code))
                cursor.execute("SELECT id FROM classrooms WHERE code = ?", (code,))
                classroom_row = cursor.fetchone()
                if not classroom_row:
                    raise RuntimeError("Failed to resolve newly created classroom.")
                try:
                    classroom_id = classroom_row["id"]
                except Exception:
                    classroom_id = classroom_row[0]

                cursor.execute("""
                    INSERT INTO classroom_internship_details (
                        classroom_id, internship_title, company_name, industry,
                        work_arrangement, compensation, location, start_date,
                        end_date, enrollment_deadline, required_hours,
                        company_website, company_description, internship_description
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    classroom_id,
                    internship_title,
                    company_name,
                    industry or None,
                    work_arrangement,
                    compensation,
                    location or None,
                    start_date,
                    end_date,
                    deadline,
                    required_hours,
                    company_website or None,
                    company_description or None,
                    internship_description,
                ))

                for sort_order, item in enumerate(responsibilities):
                    cursor.execute(
                        "INSERT INTO classroom_internship_responsibilities (classroom_id, responsibility, sort_order) VALUES (?, ?, ?)",
                        (classroom_id, item, sort_order),
                    )
                for sort_order, item in enumerate(qualifications):
                    cursor.execute(
                        "INSERT INTO classroom_internship_qualifications (classroom_id, qualification, sort_order) VALUES (?, ?, ?)",
                        (classroom_id, item, sort_order),
                    )

                conn.commit()
                flash(
                    f"Internship Classroom '{internship_title}' created with code {code}.",
                    "success",
                )
            except Exception as e:
                try:
                    conn.rollback()
                except:
                    pass
                flash(f"Failed to create internship classroom: {e}", "danger")
                return render_template(
                    "classroom/create_class.html",
                    errors={},
                    form=request.form,
                    responsibilities=responsibilities or [""],
                    qualifications=qualifications or [""],
                    initial_view="internship",
                    active_page="classes",
                )
            finally:
                try:
                    if cursor:
                        cursor.close()
                except:
                    pass
                conn.close()
            return redirect(url_for("classroom.supervisor_classes"))

        class_name = (request.form.get("class_name") or "").strip()
        section = (request.form.get("section") or "").strip()
        description = (request.form.get("description") or "").strip()
        errors = {}
        if not class_name or len(class_name) < 3 or len(class_name) > 100:
            errors["class_name"] = "Class name is required (3-100 chars)."
        if not section or len(section) < 1 or len(section) > 100:
            errors["section"] = "Section is required (1-100 chars)."
        if len(description) > 500:
            errors["description"] = "Description max 500 chars."
        if errors:
            return render_template(
                "classroom/create_class.html",
                errors=errors,
                form=request.form,
                initial_view="classroom",
                active_page="classes",
            )
        conn = get_db_connection()
        cursor = None
        try:
            cursor = conn.cursor()
            code = _generate_code(cursor)
            cursor.execute("""
                INSERT INTO classrooms
                (supervisor_id, name, section, description, code, classroom_type, archived)
                VALUES (?, ?, ?, ?, ?, 'classroom', 0)
            """, (session["user_id"], class_name, section, description, code))
            conn.commit()
            flash(f"Class '{class_name}' created with code {code}.", "success")
        except Exception as e:
            try:
                conn.rollback()
            except:
                pass
            flash(f"Failed to create class: {e}", "danger")
            return render_template(
                "classroom/create_class.html",
                errors={},
                form=request.form,
                initial_view="classroom",
                active_page="classes",
            )
        finally:
            try:
                if cursor:
                    cursor.close()
            except:
                pass
            conn.close()
        return redirect(url_for("classroom.supervisor_classes"))
    return render_template(
        "classroom/create_class.html",
        errors={},
        form={},
        responsibilities=["", ""],
        qualifications=["", ""],
        initial_view="choice",
        active_page="classes",
    )

# Supervisor: Class detail
@classroom.route("/supervisor/classes/<int:class_id>")
@role_required("supervisor")
def supervisor_class(class_id):
    sid = session["user_id"]
    conn = get_db_connection()
    try:
        c = conn.execute("SELECT id, supervisor_id, name, section, description, code, archived, created_at FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        if not c:
            conn.close()
            return "Class not found", 404
        owner = c["supervisor_id"] if "supervisor_id" in c.keys() else c[1]
        if int(owner) != int(sid):
            conn.close()
            return "Forbidden", 403
        classroom_data = {
            "id": c["id"] if "id" in c.keys() else c[0],
            "supervisor_id": owner,
            "name": c["name"] if "name" in c.keys() else c[2],
            "section": c["section"] if "section" in c.keys() else c[3],
            "description": c["description"] if "description" in c.keys() else c[4],
            "code": c["code"] if "code" in c.keys() else c[5],
            "archived": c["archived"] if "archived" in c.keys() else c[6],
            "created_at": c["created_at"] if "created_at" in c.keys() else c[7],
            "status": "Archived" if (c["archived"] if "archived" in c.keys() else c[6]) else "Active",
        }

        internship_details = conn.execute(
            """SELECT company_name, industry, work_arrangement, schedule_type,
                      hours_mode, location, start_date, end_date,
                      enrollment_deadline, required_hours, company_website
               FROM classroom_internship_details
               WHERE classroom_id = ?""",
            (class_id,),
        ).fetchone()
        detail_values = {
            "company_name": "",
            "industry": "",
            "work_arrangement": "",
            "schedule_type": "not_specified",
            "hours_mode": "not_specified",
            "location": "",
            "start_date": "",
            "end_date": "",
            "enrollment_deadline": "",
            "required_hours": 0,
            "company_website": "",
        }
        if internship_details:
            detail_keys = list(detail_values.keys())
            for index, key in enumerate(detail_keys):
                try:
                    value = internship_details[key]
                except Exception:
                    value = internship_details[index]
                if value is not None:
                    detail_values[key] = value
        classroom_data.update(detail_values)
        company_name = classroom_data["company_name"]

        linked_internship_status = {}
        if company_name:
            linked_rows = conn.execute(
                """SELECT id, student_id, status
                   FROM internships
                   WHERE supervisor_id = ?
                     AND LOWER(TRIM(COALESCE(company_name, ''))) = LOWER(TRIM(?))
                   ORDER BY student_id,
                            CASE
                                WHEN status = 'Active' THEN 0
                                WHEN status = 'Completed' THEN 1
                                WHEN status = 'Pending' THEN 2
                                ELSE 3
                            END,
                            id DESC""",
                (sid, company_name),
            ).fetchall()
            for row in linked_rows:
                student_id = row["student_id"] if "student_id" in row.keys() else row[1]
                try:
                    student_id = int(student_id)
                except (TypeError, ValueError):
                    continue
                if student_id in linked_internship_status:
                    continue
                status = row["status"] if "status" in row.keys() else row[2]
                linked_internship_status[student_id] = str(status).strip() if status else "Linked"

        cnt = conn.execute("SELECT COUNT(*) FROM classroom_students WHERE classroom_id = ?", (class_id,)).fetchone()
        student_count = cnt[0] if cnt else 0
        classroom_data["student_count"] = student_count
        posts = conn.execute("SELECT id, title, body, post_type, created_at FROM classroom_posts WHERE classroom_id = ? ORDER BY created_at DESC", (class_id,)).fetchall()
        announcements = []
        for p in posts:
            announcements.append({
                "id": p["id"] if "id" in p.keys() else p[0],
                "title": p["title"] if "title" in p.keys() else p[1],
                "body": p["body"] if "body" in p.keys() else p[2],
            })
        assigns = conn.execute("SELECT id, title, description, due_at, points, created_at FROM classroom_assignments WHERE classroom_id = ? ORDER BY created_at DESC", (class_id,)).fetchall()
        assignments = []
        for a in assigns:
            assignments.append({
                "id": a["id"] if "id" in a.keys() else a[0],
                "title": a["title"] if "title" in a.keys() else a[1],
                "description": a["description"] if "description" in a.keys() else a[2],
            })
        studs = conn.execute("""
            SELECT u.id, u.username, u.email,
                   COALESCE(sp.student_id, '') AS student_number,
                   COALESCE(sp.major_program, '') AS major_program,
                   COALESCE(sp.grade_year, '') AS grade_year
            FROM classroom_students cs
            JOIN users u ON u.id = cs.student_id
            LEFT JOIN student_profiles sp ON sp.user_id = u.id
            WHERE cs.classroom_id = ?
            ORDER BY LOWER(u.username), LOWER(u.email), u.id
        """, (class_id,)).fetchall()
        students = []
        for s in studs:
            student_user_id = s["id"] if "id" in s.keys() else s[0]
            try:
                student_user_id = int(student_user_id)
            except (TypeError, ValueError):
                pass
            email_address = s["email"] if "email" in s.keys() else s[2]
            student_number = s["student_number"] if "student_number" in s.keys() else s[3]
            major_program = s["major_program"] if "major_program" in s.keys() else s[4]
            grade_year = s["grade_year"] if "grade_year" in s.keys() else s[5]
            internship_status = linked_internship_status.get(student_user_id)
            directory_meta = []
            if email_address:
                directory_meta.append(str(email_address))
            if student_number:
                directory_meta.append(f"Student No. {student_number}")
            if major_program:
                directory_meta.append(str(major_program))
            if grade_year:
                directory_meta.append(str(grade_year))
            students.append({
                "id": student_user_id,
                "username": s["username"] if "username" in s.keys() else s[1],
                "email": " · ".join(directory_meta),
                "email_address": email_address or "",
                "student_number": student_number or "",
                "major_program": major_program or "",
                "grade_year": grade_year or "",
                "internship_status": internship_status or "Enrolled",
                "has_linked_internship": bool(internship_status),
            })
    finally:
        conn.close()
    return render_template("classroom/supervisor_class.html", classroom=classroom_data, announcements=announcements, assignments=assignments, students=students, active_page="classes")

# Supervisor: create post/announcement
@classroom.route("/supervisor/classes/<int:class_id>/post", methods=["POST"])
@role_required("supervisor")
def create_post(class_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    conn = get_db_connection()
    try:
        c = conn.execute("SELECT archived FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        if c and (c["archived"] if "archived" in c.keys() else c[0]):
            flash("Cannot post to archived class.", "warning")
            return redirect(url_for("classroom.supervisor_class", class_id=class_id))
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or request.form.get("announcement") or "").strip()
        if not body or len(body) < 3 or len(body) > 5000:
            flash("Post body is required (3-5000 chars).", "danger")
            return redirect(url_for("classroom.supervisor_class", class_id=class_id))
        if len(title) > 200:
            flash("Title max 200 chars.", "danger")
            return redirect(url_for("classroom.supervisor_class", class_id=class_id))
        conn.execute("INSERT INTO classroom_posts (classroom_id, author_id, title, body, post_type) VALUES (?, ?, ?, ?, 'announcement')", (class_id, sid, title, body))
        conn.commit()
        try:
            studs = conn.execute("SELECT student_id FROM classroom_students WHERE classroom_id = ?", (class_id,)).fetchall()
            cname_row = conn.execute("SELECT name FROM classrooms WHERE id = ?", (class_id,)).fetchone()
            cname = (cname_row["name"] if cname_row and "name" in cname_row.keys() else "Class")
            for s in studs:
                sid_stu = s["student_id"] if "student_id" in s.keys() else s[0]
                try:
                    create_notification(int(sid_stu), "New Announcement", f"New announcement in {cname}: {title or body[:60]}", "classroom", link_url=f"/student/classes/{class_id}")
                except:
                    pass
        except Exception as e:
            print("announcement notification failed:", e)
        flash("Announcement posted.", "success")
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        flash(f"Failed to post: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("classroom.supervisor_class", class_id=class_id))

# Supervisor: create assignment
@classroom.route("/supervisor/classes/<int:class_id>/assignment", methods=["POST"])
@role_required("supervisor")
def create_assignment(class_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    conn = get_db_connection()
    try:
        c = conn.execute("SELECT archived FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        if c and (c["archived"] if "archived" in c.keys() else c[0]):
            flash("Cannot add assignment to archived class.", "warning")
            return redirect(url_for("classroom.supervisor_class", class_id=class_id))
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        due_at = (request.form.get("due_at") or "").strip() or None
        points_raw = (request.form.get("points") or "").strip()
        if not title or len(title) < 3 or len(title) > 200:
            flash("Title is required (3-200 chars).", "danger")
            return redirect(url_for("classroom.supervisor_class", class_id=class_id))
        if len(description) > 5000:
            flash("Description max 5000 chars.", "danger")
            return redirect(url_for("classroom.supervisor_class", class_id=class_id))
        points = 100
        if points_raw:
            try:
                points = int(points_raw)
                if points < 0 or points > 10000:
                    raise ValueError()
            except:
                flash("Points must be 0-10000.", "danger")
                return redirect(url_for("classroom.supervisor_class", class_id=class_id))
        conn.execute("INSERT INTO classroom_assignments (classroom_id, author_id, title, description, due_at, points) VALUES (?, ?, ?, ?, ?, ?)", (class_id, sid, title, description, due_at, points))
        conn.commit()
        try:
            studs = conn.execute("SELECT student_id FROM classroom_students WHERE classroom_id = ?", (class_id,)).fetchall()
            aid_row = conn.execute("SELECT id FROM classroom_assignments WHERE classroom_id=? ORDER BY id DESC LIMIT 1", (class_id,)).fetchone()
            aid_val = (aid_row["id"] if aid_row and "id" in aid_row.keys() else (aid_row[0] if aid_row else ""))
            for s in studs:
                sid_stu = s["student_id"] if "student_id" in s.keys() else s[0]
                try:
                    create_notification(int(sid_stu), "New Assignment", f"New assignment: {title}", "classroom", link_url=f"/student/classes/{class_id}/assignments/{aid_val}")
                except:
                    pass
        except Exception as e:
            print("assignment notification failed:", e)
        flash("Assignment created.", "success")
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        flash(f"Failed to create assignment: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("classroom.supervisor_class", class_id=class_id))

# Supervisor: archive/unarchive
@classroom.route("/supervisor/classes/<int:class_id>/archive", methods=["POST"])
@role_required("supervisor")
def archive_class(class_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT archived FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        if not row:
            conn.close()
            return "Class not found", 404
        current = row["archived"] if "archived" in row.keys() else row[0]
        new_val = 0 if current else 1
        conn.execute("UPDATE classrooms SET archived = ? WHERE id = ?", (new_val, class_id))
        conn.commit()
        flash("Class archived." if new_val else "Class unarchived.", "success")
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        flash(f"Failed: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("classroom.supervisor_class", class_id=class_id))

# Student: My Classes
@classroom.route("/student/classes")
@role_required("student")
def student_classes():
    stu = session["user_id"]
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT c.id, c.name, c.section, c.description, c.code, c.archived, c.created_at,
                   u.username AS supervisor_name
            FROM classrooms c
            JOIN classroom_students cs ON cs.classroom_id = c.id
            JOIN users u ON u.id = c.supervisor_id
            WHERE cs.student_id = ? AND c.archived = 0
            ORDER BY cs.joined_at DESC
        """, (stu,)).fetchall()
        classes = []
        for r in rows:
            classes.append({
                "id": r["id"] if "id" in r.keys() else r[0],
                "name": r["name"] if "name" in r.keys() else r[1],
                "section": r["section"] if "section" in r.keys() else r[2],
                "description": r["description"] if "description" in r.keys() else r[3],
                "code": r["code"] if "code" in r.keys() else r[4],
                "archived": r["archived"] if "archived" in r.keys() else r[5],
                "status": "Active",
                "supervisor": r["supervisor_name"] if "supervisor_name" in r.keys() else r[7],
            })
    finally:
        conn.close()
    return render_template("classroom/student_classes.html", classes=classes, active_page="classes")

# Student: Join Class
@classroom.route("/student/classes/join", methods=["GET", "POST"])
@role_required("student")
def join_class():
    if request.method == "POST":
        code = (request.form.get("class_code") or request.form.get("code") or "").strip().upper()
        errors = {}
        if not code:
            errors["class_code"] = "Class code is required."
        elif len(code) < 6:
            errors["class_code"] = "Invalid class code."
        if errors:
            return render_template("classroom/join_class.html", errors=errors, form=request.form, active_page="classes")
        conn = get_db_connection()
        try:
            c = conn.execute("SELECT id, supervisor_id, archived FROM classrooms WHERE UPPER(code) = UPPER(?)", (code,)).fetchone()
            if not c:
                c2 = conn.execute("SELECT id, supervisor_id, archived FROM classrooms WHERE REPLACE(UPPER(code), '-', '') = REPLACE(UPPER(?), '-', '')", (code,)).fetchone()
                c = c2
            if not c:
                errors["class_code"] = "Invalid class code."
                return render_template("classroom/join_class.html", errors=errors, form=request.form, active_page="classes")
            cid = c["id"] if "id" in c.keys() else c[0]
            arch = c["archived"] if "archived" in c.keys() else c[2]
            if arch:
                errors["class_code"] = "Cannot join archived class."
                return render_template("classroom/join_class.html", errors=errors, form=request.form, active_page="classes")
            exists = conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ?", (cid, session["user_id"])).fetchone()
            if exists:
                flash("You are already enrolled in this class.", "info")
                return redirect(url_for("classroom.student_classes"))
            conn.execute("INSERT INTO classroom_students (classroom_id, student_id) VALUES (?, ?)", (cid, session["user_id"]))
            conn.commit()
            try:
                sup_id = c["supervisor_id"] if "supervisor_id" in c.keys() else c[1]
                u = conn.execute("SELECT username FROM users WHERE id = ?", (session["user_id"],)).fetchone()
                sname = (u["username"] if u and "username" in u.keys() else (u[0] if u else "Student"))
                cn = conn.execute("SELECT name FROM classrooms WHERE id = ?", (cid,)).fetchone()
                cname = (cn["name"] if cn and "name" in cn.keys() else "Class")
                create_notification(int(sup_id), "New Class Enrollment", f"{sname} joined your class {cname} ({code}).", "classroom", link_url=f"/supervisor/classes/{cid}")
            except Exception as e:
                print("join notification failed:", e)
            flash(f"Successfully joined class {code}.", "success")
            return redirect(url_for("classroom.student_classes"))
        except Exception as e:
            try:
                conn.rollback()
            except:
                pass
            if "UNIQUE" in str(e) or "unique" in str(e).lower():
                flash("You are already enrolled in this class.", "info")
                return redirect(url_for("classroom.student_classes"))
            flash(f"Failed to join: {e}", "danger")
            return render_template("classroom/join_class.html", errors={}, form=request.form, active_page="classes")
        finally:
            conn.close()
    return render_template("classroom/join_class.html", errors={}, form={}, active_page="classes")

# Student: Class detail
@classroom.route("/student/classes/<int:class_id>")
@role_required("student")
def student_class(class_id):
    stu = session["user_id"]
    if not _is_student_member(stu, class_id):
        return "Forbidden — not enrolled", 403
    conn = get_db_connection()
    try:
        c = conn.execute("SELECT id, supervisor_id, name, section, description, code, archived FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        if not c:
            conn.close()
            return "Class not found", 404
        sup = conn.execute("SELECT username FROM users WHERE id = ?", (c["supervisor_id"] if "supervisor_id" in c.keys() else c[1],)).fetchone()
        sup_name = (sup["username"] if sup and "username" in sup.keys() else "Supervisor")
        classroom_data = {
            "id": c["id"] if "id" in c.keys() else c[0],
            "name": c["name"] if "name" in c.keys() else c[2],
            "section": c["section"] if "section" in c.keys() else c[3],
            "description": c["description"] if "description" in c.keys() else c[4],
            "code": c["code"] if "code" in c.keys() else c[5],
            "archived": c["archived"] if "archived" in c.keys() else c[6],
            "status": "Archived" if (c["archived"] if "archived" in c.keys() else c[6]) else "Active",
            "supervisor": sup_name,
        }
        posts = conn.execute("SELECT id, title, body, created_at FROM classroom_posts WHERE classroom_id = ? ORDER BY created_at DESC", (class_id,)).fetchall()
        announcements = []
        for p in posts:
            announcements.append({
                "id": p["id"] if "id" in p.keys() else p[0],
                "title": p["title"] if "title" in p.keys() else p[1],
                "body": p["body"] if "body" in p.keys() else p[2],
            })
        assigns = conn.execute("SELECT id, title, description, due_at, points FROM classroom_assignments WHERE classroom_id = ? ORDER BY created_at DESC", (class_id,)).fetchall()
        assignments = []
        for a in assigns:
            sub = conn.execute("SELECT status, grade FROM classroom_submissions WHERE assignment_id = ? AND student_id = ?", (a["id"] if "id" in a.keys() else a[0], stu)).fetchone()
            status = (sub["status"] if sub and "status" in sub.keys() else (sub[0] if sub else "Pending")) if sub else "Pending"
            assignments.append({
                "id": a["id"] if "id" in a.keys() else a[0],
                "title": a["title"] if "title" in a.keys() else a[1],
                "description": a["description"] if "description" in a.keys() else a[2],
                "due": a["due_at"] if "due_at" in a.keys() else a[3],
                "status": status,
            })
        classmates_rows = conn.execute("""
            SELECT u.id, u.username, u.email
            FROM classroom_students cs
            JOIN users u ON u.id = cs.student_id
            WHERE cs.classroom_id = ? AND u.id != ?
            ORDER BY u.username
        """, (class_id, stu)).fetchall()
        classmates = []
        for cr in classmates_rows:
            classmates.append({
                "id": cr["id"] if "id" in cr.keys() else cr[0],
                "username": cr["username"] if "username" in cr.keys() else cr[1],
                "email": cr["email"] if "email" in cr.keys() else cr[2],
            })
    finally:
        conn.close()
    return render_template("classroom/student_class.html", classroom=classroom_data, announcements=announcements, assignments=assignments, classmates=classmates, active_page="classes")

# ========== STUDENT CLASSWORK: assignment detail + submission ==========

def _get_classroom_assignment(classroom_id, assignment_id):
    conn = get_db_connection()
    try:
        a = conn.execute("SELECT id, classroom_id, title, description, due_at, points, created_at FROM classroom_assignments WHERE id = ? AND classroom_id = ?", (assignment_id, classroom_id)).fetchone()
        return a
    finally:
        conn.close()

@classroom.route("/student/classes/<int:class_id>/assignments/<int:assignment_id>", methods=["GET"])
@role_required("student")
def student_assignment_detail(class_id, assignment_id):
    stu = session["user_id"]
    if not _is_student_member(stu, class_id):
        return "Forbidden — not enrolled", 403
    a = _get_classroom_assignment(class_id, assignment_id)
    if not a:
        return "Assignment not found", 404
    conn = get_db_connection()
    try:
        c = conn.execute("SELECT name, section FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        classroom_name = (c["name"] if c and "name" in c.keys() else "Class")
        assignment = {
            "id": a["id"] if "id" in a.keys() else a[0],
            "title": a["title"] if "title" in a.keys() else a[2],
            "description": a["description"] if "description" in a.keys() else a[3],
            "due_at": a["due_at"] if "due_at" in a.keys() else a[4],
            "points": a["points"] if "points" in a.keys() else a[5],
        }
        sub = conn.execute("SELECT id, content, filename, filepath, submitted_at, status, grade, feedback FROM classroom_submissions WHERE assignment_id = ? AND student_id = ?", (assignment_id, stu)).fetchone()
        submission = None
        if sub:
            submission = {
                "id": sub["id"] if "id" in sub.keys() else sub[0],
                "content": sub["content"] if "content" in sub.keys() else sub[1],
                "filename": sub["filename"] if "filename" in sub.keys() else sub[2],
                "filepath": sub["filepath"] if "filepath" in sub.keys() else sub[3],
                "submitted_at": sub["submitted_at"] if "submitted_at" in sub.keys() else sub[4],
                "status": sub["status"] if "status" in sub.keys() else sub[5],
                "grade": sub["grade"] if "grade" in sub.keys() else sub[6],
                "feedback": sub["feedback"] if "feedback" in sub.keys() else sub[7],
            }
        due_str = assignment["due_at"]
        past_due = False
        if due_str:
            dt = _parse_due(due_str)
            if dt and datetime.now() > dt:
                past_due = True
    finally:
        conn.close()
    return render_template("classroom/student_assignment.html", classroom={"id": class_id, "name": classroom_name}, assignment=assignment, submission=submission, past_due=past_due, active_page="classes")

@classroom.route("/student/classes/<int:class_id>/assignments/<int:assignment_id>/submit", methods=["POST"])
@role_required("student")
def student_submit_assignment(class_id, assignment_id):
    stu = session["user_id"]
    if not _is_student_member(stu, class_id):
        return "Forbidden", 403
    a = _get_classroom_assignment(class_id, assignment_id)
    if not a:
        return "Assignment not found", 404
    due_str = a["due_at"] if "due_at" in a.keys() else a[4]
    if due_str:
        dt = _parse_due(due_str)
        if dt and datetime.now() > dt:
            flash("Deadline has passed.", "danger")
            return redirect(url_for("classroom.student_assignment_detail", class_id=class_id, assignment_id=assignment_id))
    content = (request.form.get("content") or "").strip()
    file = request.files.get("file")
    filename = None
    filepath = None
    if file and file.filename:
        raw_name = secure_filename(file.filename)
        if not _allowed_classroom_file(raw_name):
            flash("File type not allowed.", "danger")
            return redirect(url_for("classroom.student_assignment_detail", class_id=class_id, assignment_id=assignment_id))
        mime, _ = mimetypes.guess_type(raw_name)
        if mime and mime.startswith("application/x-executable") or raw_name.lower().endswith((".exe",".sh",".bat",".php",".py")):
            flash("Executable files not allowed.", "danger")
            return redirect(url_for("classroom.student_assignment_detail", class_id=class_id, assignment_id=assignment_id))
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > MAX_FILE_SIZE:
            flash("File too large (max 5MB).", "danger")
            return redirect(url_for("classroom.student_assignment_detail", class_id=class_id, assignment_id=assignment_id))
        safe_name = f"{stu}_{class_id}_{assignment_id}_{raw_name}"
        base = current_app.config.get("UPLOAD_FOLDER", "") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage", "uploads")
        filepath = os.path.join(str(base), safe_name)
        if not _is_safe_path_classroom(str(base), filepath):
            flash("Invalid file path.", "danger")
            return redirect(url_for("classroom.student_assignment_detail", class_id=class_id, assignment_id=assignment_id))
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file.save(filepath)
        filename = safe_name
    if not content and not filename:
        flash("Submit text or file is required.", "danger")
        return redirect(url_for("classroom.student_assignment_detail", class_id=class_id, assignment_id=assignment_id))
    if content and len(content) > 10000:
        flash("Content too long (max 10000 chars).", "danger")
        return redirect(url_for("classroom.student_assignment_detail", class_id=class_id, assignment_id=assignment_id))
    conn = get_db_connection()
    try:
        existing = conn.execute("SELECT id, filepath FROM classroom_submissions WHERE assignment_id = ? AND student_id = ?", (assignment_id, stu)).fetchone()
        if existing:
            old_path = existing["filepath"] if "filepath" in existing.keys() else existing[1]
            if filename and old_path and os.path.exists(old_path) and old_path != filepath:
                try:
                    os.remove(old_path)
                except:
                    pass
            if not filename:
                filename = existing["filename"] if "filename" in existing.keys() else None
                filepath = existing["filepath"] if "filepath" in existing.keys() else None
            conn.execute("UPDATE classroom_submissions SET content = ?, filename = ?, filepath = ?, submitted_at = CURRENT_TIMESTAMP, status = 'submitted' WHERE assignment_id = ? AND student_id = ?", (content, filename, filepath, assignment_id, stu))
        else:
            conn.execute("INSERT INTO classroom_submissions (assignment_id, student_id, content, filename, filepath, status) VALUES (?, ?, ?, ?, ?, 'submitted')", (assignment_id, stu, content, filename, filepath))
        conn.commit()
        try:
            c = conn.execute("SELECT supervisor_id, name FROM classrooms WHERE id = ?", (class_id,)).fetchone()
            sup_id = (c["supervisor_id"] if c and "supervisor_id" in c.keys() else None)
            if sup_id:
                u = conn.execute("SELECT username FROM users WHERE id = ?", (stu,)).fetchone()
                sname = (u["username"] if u and "username" in u.keys() else "Student")
                a_title = (a["title"] if "title" in a.keys() else "assignment")
                create_notification(int(sup_id), "Classwork Submitted", f"{sname} submitted {a_title} in classroom.", "classroom", link_url=f"/supervisor/classes/{class_id}/assignments/{assignment_id}")
        except Exception as e:
            print("classroom submit notification failed:", e)
        flash("Submission saved.", "success")
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        flash(f"Failed to submit: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("classroom.student_assignment_detail", class_id=class_id, assignment_id=assignment_id))

# ========== SUPERVISOR CLASSWORK: assignment view, submissions, grading ==========

@classroom.route("/supervisor/classes/<int:class_id>/assignments/<int:assignment_id>")
@role_required("supervisor")
def supervisor_assignment_detail(class_id, assignment_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    a = _get_classroom_assignment(class_id, assignment_id)
    if not a:
        return "Assignment not found", 404
    conn = get_db_connection()
    try:
        assignment = {
            "id": a["id"] if "id" in a.keys() else a[0],
            "title": a["title"] if "title" in a.keys() else a[2],
            "description": a["description"] if "description" in a.keys() else a[3],
            "due_at": a["due_at"] if "due_at" in a.keys() else a[4],
            "points": a["points"] if "points" in a.keys() else a[5],
        }
        enrolled = conn.execute("SELECT COUNT(*) FROM classroom_students WHERE classroom_id = ?", (class_id,)).fetchone()[0]
        submitted = conn.execute("SELECT COUNT(*) FROM classroom_submissions WHERE assignment_id = ?", (assignment_id,)).fetchone()[0]
        missing = max(0, enrolled - submitted)
        subs = conn.execute("""
            SELECT cs.id, cs.student_id, cs.content, cs.filename, cs.filepath, cs.submitted_at, cs.status, cs.grade, cs.feedback, u.username, u.email
            FROM classroom_submissions cs
            JOIN users u ON u.id = cs.student_id
            WHERE cs.assignment_id = ?
            ORDER BY cs.submitted_at DESC
        """, (assignment_id,)).fetchall()
        submissions = []
        for s in subs:
            submissions.append({
                "id": s["id"] if "id" in s.keys() else s[0],
                "student_id": s["student_id"] if "student_id" in s.keys() else s[1],
                "content": s["content"] if "content" in s.keys() else s[2],
                "filename": s["filename"] if "filename" in s.keys() else s[3],
                "filepath": s["filepath"] if "filepath" in s.keys() else s[4],
                "submitted_at": s["submitted_at"] if "submitted_at" in s.keys() else s[5],
                "status": s["status"] if "status" in s.keys() else s[6],
                "grade": s["grade"] if "grade" in s.keys() else s[7],
                "feedback": s["feedback"] if "feedback" in s.keys() else s[8],
                "username": s["username"] if "username" in s.keys() else s[9],
                "email": s["email"] if "email" in s.keys() else s[10],
            })
        c = conn.execute("SELECT name FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        cname = (c["name"] if c and "name" in c.keys() else "Class")
    finally:
        conn.close()
    return render_template("classroom/supervisor_assignment.html", classroom={"id": class_id, "name": cname}, assignment=assignment, submissions=submissions, enrolled=enrolled, submitted=submitted, missing=missing, active_page="classes")

@classroom.route("/supervisor/classes/<int:class_id>/assignments/<int:assignment_id>/submissions/<int:submission_id>")
@role_required("supervisor")
def supervisor_submission_detail(class_id, assignment_id, submission_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    a = _get_classroom_assignment(class_id, assignment_id)
    if not a:
        return "Assignment not found", 404
    conn = get_db_connection()
    try:
        sub = conn.execute("SELECT id, assignment_id, student_id, content, filename, filepath, submitted_at, status, grade, feedback FROM classroom_submissions WHERE id = ? AND assignment_id = ?", (submission_id, assignment_id)).fetchone()
        if not sub:
            conn.close()
            return "Submission not found", 404
        stu = conn.execute("SELECT username, email FROM users WHERE id = ?", (sub["student_id"] if "student_id" in sub.keys() else sub[2],)).fetchone()
        student = {
            "id": sub["student_id"] if "student_id" in sub.keys() else sub[2],
            "username": stu["username"] if stu and "username" in stu.keys() else "Student",
            "email": stu["email"] if stu and "email" in stu.keys() else "",
        }
        submission = {
            "id": sub["id"] if "id" in sub.keys() else sub[0],
            "content": sub["content"] if "content" in sub.keys() else sub[3],
            "filename": sub["filename"] if "filename" in sub.keys() else sub[4],
            "filepath": sub["filepath"] if "filepath" in sub.keys() else sub[5],
            "submitted_at": sub["submitted_at"] if "submitted_at" in sub.keys() else sub[6],
            "status": sub["status"] if "status" in sub.keys() else sub[7],
            "grade": sub["grade"] if "grade" in sub.keys() else sub[8],
            "feedback": sub["feedback"] if "feedback" in sub.keys() else sub[9],
        }
        assignment = {
            "id": a["id"] if "id" in a.keys() else a[0],
            "title": a["title"] if "title" in a.keys() else a[2],
        }
    finally:
        conn.close()
    return render_template("classroom/supervisor_submission.html", classroom={"id": class_id}, assignment=assignment, submission=submission, student=student, active_page="classes")

@classroom.route("/supervisor/classes/<int:class_id>/assignments/<int:assignment_id>/submissions/<int:submission_id>/grade", methods=["POST"])
@role_required("supervisor")
def grade_submission(class_id, assignment_id, submission_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    a = _get_classroom_assignment(class_id, assignment_id)
    if not a:
        return "Assignment not found", 404
    grade = (request.form.get("grade") or "").strip()
    feedback = (request.form.get("feedback") or "").strip()
    if grade and len(grade) > 20:
        flash("Grade too long (max 20 chars).", "danger")
        return redirect(url_for("classroom.supervisor_submission_detail", class_id=class_id, assignment_id=assignment_id, submission_id=submission_id))
    if len(feedback) > 2000:
        flash("Feedback too long (max 2000 chars).", "danger")
        return redirect(url_for("classroom.supervisor_submission_detail", class_id=class_id, assignment_id=assignment_id, submission_id=submission_id))
    conn = get_db_connection()
    try:
        sub = conn.execute("SELECT student_id FROM classroom_submissions WHERE id = ? AND assignment_id = ?", (submission_id, assignment_id)).fetchone()
        if not sub:
            conn.close()
            return "Submission not found", 404
        student_id = sub["student_id"] if "student_id" in sub.keys() else sub[0]
        conn.execute("UPDATE classroom_submissions SET grade = ?, feedback = ?, status = 'graded' WHERE id = ? AND assignment_id = ?", (grade, feedback, submission_id, assignment_id))
        conn.commit()
        try:
            a_title = (a["title"] if "title" in a.keys() else "assignment")
            create_notification(int(student_id), "Submission Graded", f"Your submission for {a_title} was graded.", "classroom", link_url=f"/student/classes/{class_id}/assignments/{assignment_id}")
        except Exception as e:
            print("grade notification failed:", e)
        flash("Submission graded.", "success")
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        flash(f"Failed to grade: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("classroom.supervisor_submission_detail", class_id=class_id, assignment_id=assignment_id, submission_id=submission_id))

@classroom.route("/supervisor/classes/<int:class_id>/assignments/<int:assignment_id>/submissions/<int:submission_id>/download")
@role_required("supervisor")
def download_submission_supervisor(class_id, assignment_id, submission_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    a = _get_classroom_assignment(class_id, assignment_id)
    if not a:
        return "Assignment not found", 404
    conn = get_db_connection()
    try:
        sub = conn.execute("SELECT filename, filepath FROM classroom_submissions WHERE id = ? AND assignment_id = ?", (submission_id, assignment_id)).fetchone()
        if not sub:
            return "Submission not found", 404
        filename = sub["filename"] if "filename" in sub.keys() else sub[0]
        filepath = sub["filepath"] if "filepath" in sub.keys() else sub[1]
        if not filepath or not filename:
            return "No file attached", 404
        base = current_app.config.get("UPLOAD_FOLDER", "")
        if base and not _is_safe_path_classroom(base, filepath):
            return "Invalid file path", 403
        if not os.path.exists(filepath):
            return "File not found", 404
        return send_file(filepath, as_attachment=True, download_name=filename)
    finally:
        conn.close()

@classroom.route("/student/classes/<int:class_id>/assignments/<int:assignment_id>/download")
@role_required("student")
def download_own_submission(class_id, assignment_id):
    stu = session["user_id"]
    if not _is_student_member(stu, class_id):
        return "Forbidden", 403
    a = _get_classroom_assignment(class_id, assignment_id)
    if not a:
        return "Assignment not found", 404
    conn = get_db_connection()
    try:
        sub = conn.execute("SELECT filename, filepath FROM classroom_submissions WHERE assignment_id = ? AND student_id = ?", (assignment_id, stu)).fetchone()
        if not sub:
            return "Submission not found", 404
        filename = sub["filename"] if "filename" in sub.keys() else sub[0]
        filepath = sub["filepath"] if "filepath" in sub.keys() else sub[1]
        if not filepath or not filename:
            return "No file attached", 404
        base = current_app.config.get("UPLOAD_FOLDER", "")
        if base and not _is_safe_path_classroom(base, filepath):
            return "Invalid file path", 403
        if not os.path.exists(filepath):
            return "File not found", 404
        return send_file(filepath, as_attachment=True, download_name=filename)
    finally:
        conn.close()

# Supervisor: regenerate class code (secure)
@classroom.route("/supervisor/classes/<int:class_id>/regenerate", methods=["POST"])
@role_required("supervisor")
def regenerate_code(class_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    conn = get_db_connection()
    try:
        c = conn.execute("SELECT code FROM classrooms WHERE id = ?", (class_id,)).fetchone()
        if not c:
            conn.close()
            return "Class not found", 404
        old_code = c["code"] if "code" in c.keys() else c[0]
        cursor = conn.cursor()
        new_code = _generate_code(cursor)
        cursor.execute("UPDATE classrooms SET code = ? WHERE id = ?", (new_code, class_id))
        conn.commit()
        try:
            studs = conn.execute("SELECT student_id FROM classroom_students WHERE classroom_id = ?", (class_id,)).fetchall()
            cname_row = conn.execute("SELECT name FROM classrooms WHERE id = ?", (class_id,)).fetchone()
            cname = (cname_row["name"] if cname_row and "name" in cname_row.keys() else "Class")
            for s in studs:
                stu_id = s["student_id"] if "student_id" in s.keys() else s[0]
                try:
                    create_notification(int(stu_id), "Class Code Updated", f"Class {cname} code changed from {old_code} to {new_code}.", "classroom", link_url=f"/student/classes/{class_id}")
                except:
                    pass
        except Exception as e:
            print("regenerate notification failed:", e)
        flash(f"Class code regenerated: {new_code}", "success")
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        flash(f"Failed to regenerate: {e}", "danger")
    finally:
        try:
            cursor.close()
        except:
            pass
        conn.close()
    return redirect(url_for("classroom.supervisor_class", class_id=class_id))

# Supervisor: remove student from class
@classroom.route("/supervisor/classes/<int:class_id>/students/<int:student_id>/remove", methods=["POST"])
@role_required("supervisor")
def remove_student(class_id, student_id):
    sid = session["user_id"]
    if not _is_supervisor_owner(sid, class_id):
        return "Forbidden", 403
    if int(student_id) == int(sid):
        flash("Cannot remove yourself.", "danger")
        return redirect(url_for("classroom.supervisor_class", class_id=class_id))
    conn = get_db_connection()
    try:
        exists = conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ?", (class_id, student_id)).fetchone()
        if not exists:
            flash("Student not enrolled in this class.", "warning")
            return redirect(url_for("classroom.supervisor_class", class_id=class_id))
        conn.execute("DELETE FROM classroom_students WHERE classroom_id = ? AND student_id = ?", (class_id, student_id))
        conn.commit()
        try:
            cname_row = conn.execute("SELECT name FROM classrooms WHERE id = ?", (class_id,)).fetchone()
            cname = (cname_row["name"] if cname_row and "name" in cname_row.keys() else "Class")
            create_notification(int(student_id), "Removed from Class", f"You were removed from {cname}.", "classroom", link_url="/student/classes")
        except Exception as e:
            print("remove notification failed:", e)
        flash("Student removed from class.", "success")
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        flash(f"Failed to remove: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("classroom.supervisor_class", class_id=class_id))
