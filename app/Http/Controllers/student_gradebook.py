from flask import Blueprint, abort, render_template, session

from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection
from app.Services.classwork_grade_calculator import calculate_overall

student_gradebook = Blueprint("student_gradebook", __name__)


def _value(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            return row[key]
    except AttributeError:
        pass
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return default


def _activity_label(activity_type):
    return {"assignment":"Assignment","google_form":"Google Form / Quiz","google_doc":"Google Docs / Sheets","file_reference":"File / Reference","project":"Project","group_project":"Group Project"}.get(activity_type or "assignment", "Assignment")


@student_gradebook.route("/student/classes/<int:class_id>/gradebook")
@role_required("student")
def gradebook(class_id):
    student_id = session["user_id"]
    conn = get_db_connection()
    try:
        classroom = conn.execute("""SELECT c.id, c.name, c.section, c.supervisor_id, c.archived, u.username AS supervisor_name
           FROM classrooms c JOIN users u ON u.id=c.supervisor_id JOIN classroom_students cs ON cs.classroom_id=c.id
           WHERE c.id=? AND cs.student_id=?""", (class_id, student_id)).fetchone()
        if not classroom:
            abort(404)

        assignments = conn.execute("""SELECT a.id, a.title, a.points, a.due_at, a.created_at, m.activity_type,
               s.score AS normalized_score, s.max_score AS normalized_max_score, s.percentage AS normalized_percentage,
               s.grading_method AS normalized_method, sub.grade AS submission_grade, sub.status AS submission_status
           FROM classroom_assignments a
           LEFT JOIN classroom_assignment_meta m ON m.assignment_id=a.id
           LEFT JOIN classwork_scores s ON s.assignment_id=a.id AND s.student_id=?
           LEFT JOIN LATERAL (
               SELECT grade, status FROM classwork_submissions cs
               WHERE cs.assignment_id=a.id AND cs.student_id=? ORDER BY cs.attempt_no DESC, cs.id DESC LIMIT 1
           ) sub ON TRUE
           WHERE a.classroom_id=? ORDER BY a.created_at ASC, a.id ASC""", (student_id, student_id, class_id)).fetchall()

        # SQLite has no LATERAL in some installations; use a portable fallback if needed.
        if assignments is None:
            assignments = []
    except Exception:
        # Portable query for SQLite and older schemas.
        assignments = conn.execute("""SELECT a.id, a.title, a.points, a.due_at, a.created_at, m.activity_type,
               s.score AS normalized_score, s.max_score AS normalized_max_score, s.percentage AS normalized_percentage,
               s.grading_method AS normalized_method, NULL AS submission_grade, NULL AS submission_status
           FROM classroom_assignments a LEFT JOIN classroom_assignment_meta m ON m.assignment_id=a.id
           LEFT JOIN classwork_scores s ON s.assignment_id=a.id AND s.student_id=?
           WHERE a.classroom_id=? ORDER BY a.created_at ASC, a.id ASC""", (student_id, class_id)).fetchall()
        for idx, assignment in enumerate(assignments):
            aid = int(_value(assignment, "id", 0))
            sub = conn.execute("SELECT grade, status FROM classwork_submissions WHERE assignment_id=? AND student_id=? ORDER BY attempt_no DESC, id DESC LIMIT 1", (aid, student_id)).fetchone()
            values = list(assignment)
            values[10] = _value(sub, "grade", 0) if sub else None
            values[11] = _value(sub, "status", 1) if sub else None
            assignments[idx] = type(assignment)(values) if not hasattr(assignment, 'keys') else assignment

        grade_records=[]; activities=[]
        for assignment in assignments:
            aid=int(_value(assignment,"id",0)); points=float(_value(assignment,"points",2,0) or 0)
            score=_value(assignment,"normalized_score",6)
            max_score=_value(assignment,"normalized_max_score",7)
            percentage=_value(assignment,"normalized_percentage",8)
            method=_value(assignment,"normalized_method",9)
            submission_grade=_value(assignment,"submission_grade",10)
            submission_status=_value(assignment,"submission_status",11)
            # Legacy/older graded submissions are authoritative when normalized score is absent.
            if score is None and submission_grade is not None:
                score=float(submission_grade); max_score=points; percentage=(score/max_score*100) if max_score else 0; method=method or "manual"
            if score is not None and max_score is None: max_score=points
            if score is not None:
                score=float(score); max_score=float(max_score or points or 0)
                if percentage is None: percentage=(score/max_score*100) if max_score else 0
                grade_records.append({"score":score,"max_score":max_score}); graded=True
                score_display=f"{score:g} / {max_score:g}"; percentage_display=f"{float(percentage):.1f}%"; grading_method=method or "manual"
            else:
                graded=False; score_display="—"; percentage_display="—"; grading_method=None
            activities.append({"id":aid,"title":_value(assignment,"title",1,"Activity"),"activity_label":_activity_label(_value(assignment,"activity_type",5)),"due_at":_value(assignment,"due_at",3),"points":points,"graded":graded,"score_display":score_display,"percentage_display":percentage_display,"grading_method":grading_method,"submission_status":submission_status})

        summary=calculate_overall(grade_records)
        classroom_data={"id":_value(classroom,"id",0),"name":_value(classroom,"name",1),"section":_value(classroom,"section",2),"supervisor":_value(classroom,"supervisor_name",5),"archived":bool(_value(classroom,"archived",4,0))}
    finally:
        conn.close()

    return render_template("classroom/student_gradebook.html", classroom=classroom_data, activities=activities, graded_count=summary["graded_count"], total_count=len(activities), earned=summary["earned"], possible=summary["possible"], overall=summary["overall"], overall_display=f"{summary['overall']:.1f}%" if summary["overall"] is not None else "—", active_page="classes")
