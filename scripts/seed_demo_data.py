"""Safe, idempotent Nexora demo-data seed.

Dry-run is the default. Set NEXORA_DEMO_SEED_APPLY=true to write.
This script never changes database schema and never deletes classrooms/users.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.Models.db import get_db_connection, using_postgres
from app.Services.password_security import hash_password

TAG = "[DEMO SEED]"
TARGET_CLASSROOMS = int(os.environ.get("NEXORA_DEMO_CLASSROOMS", "4"))
TARGET_STUDENTS = int(os.environ.get("NEXORA_DEMO_STUDENTS_PER_CLASS", "20"))
APPLY = os.environ.get("NEXORA_DEMO_SEED_APPLY", "").strip().lower() == "true"
PASSWORD = os.environ.get("NEXORA_DEMO_PASSWORD", "")

FIRST = ["Andrea","Miguel","Sofia","Joshua","Bianca","Carlo","Alyssa","Nathan","Camille","Adrian","Patricia","Daniel","Nicole","Gabriel","Jasmine","Marco","Trisha","Paolo","Clarisse","Vincent"]
MIDDLE = ["Mae","Luis","Anne","Paolo","Grace","Miguel","Rose","James","Louise","Reyes","Joy","Martin","Marie","Angelo","Faith","Jose","Mae","Luis","Anne","Rafael"]
LAST = ["Santos","Reyes","Cruz","Garcia","Mendoza","Bautista","Flores","Ramos","Aquino","Navarro","Castillo","Torres","Villanueva","Fernandez","Morales","Herrera","Dela Cruz","Mercado","Salazar","Dominguez"]
ADDRESSES = ["Pasig City, Metro Manila","Quezon City, Metro Manila","Mandaluyong City, Metro Manila","Taguig City, Metro Manila","Marikina City, Metro Manila"]
POSITIONS = ["Software Development Intern","Quality Assurance Intern","UI/UX Design Intern","Data Operations Intern","Technical Support Intern"]

WORK_ITEMS = [
    ("[Demo] Company Orientation Brief","Summarize the company, team, tools, and internship expectations.","2026-09-25 17:00:00"),
    ("[Demo] Weekly Progress Report","Document completed work, blockers, lessons learned, and next steps.","2026-10-02 17:00:00"),
    ("[Demo] Process Improvement Proposal","Identify one workflow improvement and support it with evidence.","2026-10-09 17:00:00"),
    ("[Demo] Midterm Internship Reflection","Reflect on competencies developed and areas that still need practice.","2026-10-16 17:00:00"),
    ("[Demo] Portfolio and Final Demonstration","Prepare a concise portfolio of internship outputs and outcomes.","2026-11-20 17:00:00"),
]
TASK_ITEMS = [
    ("[Demo] Update weekly internship journal","Record this week's accomplishments and reflection.","2026-10-14 17:00:00","Pending"),
    ("[Demo] Review supervisor feedback","Read the latest supervisor feedback and note your action items.","2026-10-05 17:00:00","Reviewed"),
    ("[Demo] Prepare next progress checkpoint","Prepare the evidence needed for the next internship progress review.","2026-10-01 17:00:00","Overdue"),
]
POST_ITEMS = [
    ("[Demo] Welcome to the Intern Classroom","Welcome interns. Review the Stream, Classwork, Gradebook, Logbook, and internship schedule before starting weekly work."),
    ("[Demo] Weekly OJT Reminder","Complete attendance, document your Daily Logbook, link the Work you handled, and review supervisor feedback."),
]
SCORE_DELTA = (-2.0,0.0,1.5,2.0,-1.0)
DAY_DELTA = (-1.5,0.0,1.0,-0.5,1.5,0.5)
ATTENDANCE_START = datetime(2026,9,21,9,0,0)


def getv(row, key, index=0, default=None):
    if row is None:
        return default
    try:
        if key in row.keys():
            value = row[key]
            return default if value is None else value
    except Exception:
        pass
    try:
        value = row[index]
        return default if value is None else value
    except Exception:
        return default


def table_exists(conn, name):
    if using_postgres():
        return bool(conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=? LIMIT 1",
            (name,),
        ).fetchone())
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone())


def columns(conn, name):
    if not table_exists(conn, name):
        return set()
    if using_postgres():
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=? ORDER BY ordinal_position",
            (name,),
        ).fetchall()
        return {str(getv(row,"column_name",0,"")) for row in rows}
    rows = conn.execute("PRAGMA table_info(" + name + ")").fetchall()
    return {str(getv(row,"name",1,"")) for row in rows}


def blank(value):
    return value is None or (isinstance(value,str) and not value.strip())


def demo_username(username):
    text = str(username or "").strip().lower()
    return text.startswith("demo") or text.startswith("seed_c")


def clamp(value, low=0.0, high=100.0):
    return max(low,min(high,float(value)))


def base_score(slot):
    pos=((slot-1)%5)+1
    band={1:70.0,2:80.0,3:86.0,4:93.0,5:96.0}[pos]
    return band + ((slot-1)//5)%2


def label(score):
    score=float(score)
    if score>=90:return "Excellent"
    if score>=85:return "Very Satisfactory"
    if score>=75:return "Satisfactory"
    if score>=60:return "Fair"
    return "Needs Improvement"


def star_for(score):
    score=clamp(score,60,100)
    anchors=[(60,1.0),(70,2.0),(80,3.0),(90,4.0),(96,4.7),(100,5.0)]
    for i in range(len(anchors)-1):
        p1,s1=anchors[i]; p2,s2=anchors[i+1]
        if p1<=score<=p2:
            return round(s1+((score-p1)/(p2-p1))*(s2-s1),1)
    return 5.0


def active_classrooms(conn):
    return conn.execute(
        """
        SELECT c.id,c.supervisor_id,c.name,c.section,
               u.username AS supervisor_username,u.email AS supervisor_email
        FROM classrooms c
        JOIN users u ON u.id=c.supervisor_id
        WHERE COALESCE(c.archived,0)=0
        ORDER BY c.id
        """
    ).fetchall()


def roster_count(conn,class_id):
    row=conn.execute("SELECT COUNT(*) AS total FROM classroom_students WHERE classroom_id=?",(class_id,)).fetchone()
    return int(getv(row,"total",0,0) or 0)


def find_user(conn,username):
    return conn.execute("SELECT id,username,email,role,status,password_changed_at FROM users WHERE username=? LIMIT 1",(username,)).fetchone()


def enroll(conn,class_id,student_id):
    if not conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id=? AND student_id=? LIMIT 1",(class_id,student_id)).fetchone():
        conn.execute("INSERT INTO classroom_students (classroom_id,student_id,joined_at) VALUES (?,?,CURRENT_TIMESTAMP)",(class_id,student_id))


def create_seed_user(conn,class_id,slot,password_hash):
    username=f"seed_c{class_id}_s{slot:02d}"
    row=find_user(conn,username)
    if row:
        if str(getv(row,"role",3,""))!="student":
            raise RuntimeError(f"Seed username collision: {username}")
        student_id=int(getv(row,"id",0,0))
        enroll(conn,class_id,student_id)
        return student_id
    email=f"seed.c{class_id}.s{slot:02d}@nexora.demo"
    conn.execute(
        """INSERT INTO users (username,email,password,role,status,password_changed_at,created_at)
           VALUES (?,?,?,'student','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
        (username,email,password_hash),
    )
    row=find_user(conn,username)
    if not row: raise RuntimeError(f"Could not create {username}")
    student_id=int(getv(row,"id",0,0))
    enroll(conn,class_id,student_id)
    return student_id


def backfill_student_account(conn,student_id,class_id):
    row=conn.execute("SELECT id,username,email,role,status,password_changed_at FROM users WHERE id=?",(student_id,)).fetchone()
    if not row or str(getv(row,"role",3,"") or "")!="student": return
    updates=[]; params=[]
    if blank(getv(row,"email",2,None)):
        updates.append("email=?"); params.append(f"student.c{class_id}.u{student_id}@nexora.demo")
    if blank(getv(row,"status",4,None)): updates.append("status='active'")
    if getv(row,"password_changed_at",5,None) is None: updates.append("password_changed_at=CURRENT_TIMESTAMP")
    if updates:
        params.append(student_id)
        conn.execute("UPDATE users SET "+", ".join(updates)+" WHERE id=?",tuple(params))


def backfill_profile(conn,student_id,class_id,slot):
    row=conn.execute("SELECT username,email,role FROM users WHERE id=?",(student_id,)).fetchone()
    if not row or str(getv(row,"role",2,"") or "")!="student": return
    username=str(getv(row,"username",0,"") or f"student{student_id}")
    email=str(getv(row,"email",1,"") or "")
    idx=(slot-1)%20

    preferred_student_number=f"NXR-{class_id:02d}-{slot:03d}"
    collision=conn.execute(
        "SELECT user_id FROM student_profiles WHERE student_id=? AND user_id<>? LIMIT 1",
        (preferred_student_number,student_id),
    ).fetchone()
    generated_student_number=(
        f"NXR-{class_id:02d}-U{student_id:05d}"
        if collision else preferred_student_number
    )

    data={
        "first_name":FIRST[idx],"middle_name":MIDDLE[idx],"last_name":LAST[(idx+class_id-1)%20],
        "age":20+(slot%4),"student_id":generated_student_number,
        "school_email":email or f"{username}@nexora.demo",
        "phone_number":f"0917{class_id:02d}{slot:05d}"[-11:],
        "home_address":ADDRESSES[idx%len(ADDRESSES)],"grade_year":"4th Year",
        "major_program":"BS Information Technology",
        "emergency_name":f"{FIRST[idx]} {LAST[(idx+class_id-1)%20]} Guardian",
        "emergency_relationship":"Parent",
        "emergency_phone":f"0928{class_id:02d}{slot:05d}"[-11:],
        "emergency_email":f"guardian.c{class_id}.s{slot:02d}@nexora.demo",
        "profile_completed":1,
    }
    cols=columns(conn,"student_profiles")
    existing=conn.execute("SELECT * FROM student_profiles WHERE user_id=? LIMIT 1",(student_id,)).fetchone()
    if not existing:
        keys=["user_id"]+[key for key in data if key in cols]
        vals=[student_id]+[data[key] for key in keys[1:]]
        conn.execute(f"INSERT INTO student_profiles ({', '.join(keys)}) VALUES ({', '.join(['?']*len(keys))})",tuple(vals))
        return
    updates=[]; params=[]
    for key,new_value in data.items():
        if key not in cols: continue
        current=getv(existing,key,0,None)
        missing=blank(current) or (key=="profile_completed" and not bool(current))
        if missing:
            updates.append(f"{key}=?"); params.append(new_value)
    if updates:
        params.append(student_id)
        conn.execute("UPDATE student_profiles SET "+", ".join(updates)+" WHERE user_id=?",tuple(params))


def company_for(conn,class_id,class_name):
    if table_exists(conn,"classroom_internship_details") and "company_name" in columns(conn,"classroom_internship_details"):
        row=conn.execute("SELECT company_name FROM classroom_internship_details WHERE classroom_id=? LIMIT 1",(class_id,)).fetchone()
        company=str(getv(row,"company_name",0,"") or "").strip()
        if company:return company
    return class_name+" Partner Company"


def ensure_assignment_link(conn,student_id,supervisor_id):
    if not conn.execute("SELECT 1 FROM student_assignments WHERE student_id=? AND supervisor_id=? LIMIT 1",(student_id,supervisor_id)).fetchone():
        conn.execute("INSERT INTO student_assignments (student_id,supervisor_id) VALUES (?,?)",(student_id,supervisor_id))


def ensure_internship(conn,student_id,supervisor_id,supervisor_name,supervisor_email,company,slot):
    row=conn.execute("SELECT * FROM internships WHERE student_id=? AND supervisor_id=? ORDER BY id LIMIT 1",(student_id,supervisor_id)).fetchone()
    data={
        "company_name":company,"company_address":ADDRESSES[(slot-1)%len(ADDRESSES)],
        "supervisor_name":supervisor_name or "Nexora Supervisor",
        "supervisor_email":supervisor_email or "supervisor@nexora.demo",
        "supervisor_id":supervisor_id,"position":POSITIONS[(slot-1)%len(POSITIONS)],
        "start_date":"2026-08-03","end_date":"2026-12-18",
        "required_hours":486,"completed_hours":48,"status":"Active",
    }
    cols=columns(conn,"internships")
    if not row:
        keys=["student_id"]+[key for key in data if key in cols]
        vals=[student_id]+[data[key] for key in keys[1:]]
        conn.execute(f"INSERT INTO internships ({', '.join(keys)}) VALUES ({', '.join(['?']*len(keys))})",tuple(vals))
        return
    updates=[]; params=[]
    for key,new_value in data.items():
        if key not in cols: continue
        current=getv(row,key,0,None)
        if blank(current) or (key=="completed_hours" and float(current or 0)<=0):
            updates.append(f"{key}=?"); params.append(new_value)
    if updates:
        params.append(int(getv(row,"id",0,0)))
        conn.execute("UPDATE internships SET "+", ".join(updates)+" WHERE id=?",tuple(params))


def ensure_posts(conn,class_id,supervisor_id):
    for title,body in POST_ITEMS:
        if not conn.execute("SELECT 1 FROM classroom_posts WHERE classroom_id=? AND title=? LIMIT 1",(class_id,title)).fetchone():
            conn.execute(
                """INSERT INTO classroom_posts (classroom_id,author_id,title,body,post_type,created_at)
                   VALUES (?,?,?,?,'announcement',CURRENT_TIMESTAMP)""",
                (class_id,supervisor_id,title,body),
            )


def ensure_work_items(conn,class_id,supervisor_id):
    ids=[]
    for title,description,due_at in WORK_ITEMS:
        row=conn.execute("SELECT id FROM classroom_assignments WHERE classroom_id=? AND title=? LIMIT 1",(class_id,title)).fetchone()
        if not row:
            conn.execute(
                """INSERT INTO classroom_assignments
                   (classroom_id,author_id,title,description,due_at,points,created_at)
                   VALUES (?,?,?,?,?,100,CURRENT_TIMESTAMP)""",
                (class_id,supervisor_id,title,description,due_at),
            )
            row=conn.execute("SELECT id FROM classroom_assignments WHERE classroom_id=? AND title=? LIMIT 1",(class_id,title)).fetchone()
        if not row: raise RuntimeError(f"Could not resolve Work item {title}")
        ids.append(int(getv(row,"id",0,0)))
    return ids


def ensure_work_scores(conn,student_id,assignment_ids,score_base):
    for idx,assignment_id in enumerate(assignment_ids):
        pct=round(clamp(score_base+SCORE_DELTA[idx%len(SCORE_DELTA)],60,100),1)
        if not conn.execute("SELECT 1 FROM classwork_scores WHERE assignment_id=? AND student_id=? LIMIT 1",(assignment_id,student_id)).fetchone():
            conn.execute(
                """INSERT INTO classwork_scores
                   (assignment_id,student_id,score,max_score,percentage,grading_method,imported_at)
                   VALUES (?,?,?,100,?,'manual',CURRENT_TIMESTAMP)""",
                (assignment_id,student_id,pct,pct),
            )
        if not conn.execute("SELECT 1 FROM classroom_submissions WHERE assignment_id=? AND student_id=? LIMIT 1",(assignment_id,student_id)).fetchone():
            conn.execute(
                """INSERT INTO classroom_submissions
                   (assignment_id,student_id,content,submitted_at,status,grade,feedback)
                   VALUES (?,?,?,CURRENT_TIMESTAMP,'Reviewed',?,?)""",
                (assignment_id,student_id,f"{TAG} Completed internship evidence for Work item {idx+1}.",f"{pct:.1f}",f"{TAG} Reviewed by the supervisor; apply this feedback in the next Work item."),
            )


def ensure_tasks(conn,student_id,supervisor_id):
    for title,description,deadline,status in TASK_ITEMS:
        if not conn.execute("SELECT 1 FROM tasks WHERE student_id=? AND supervisor_id=? AND task_title=? LIMIT 1",(student_id,supervisor_id,title)).fetchone():
            conn.execute(
                """INSERT INTO tasks
                   (student_id,supervisor_id,task_title,task_description,assigned_at,deadline,requires_submission,allow_late_submission,status)
                   VALUES (?,?,?,?,CURRENT_TIMESTAMP,?,1,1,?)""",
                (student_id,supervisor_id,title,description,deadline,status),
            )


def ensure_attendance_logbook(conn,student_id,class_id,supervisor_id,assignment_ids,score_base):
    for day in range(6):
        clock_in=ATTENDANCE_START+timedelta(days=day)
        clock_out=clock_in+timedelta(hours=8)
        date_text=clock_in.date().isoformat()
        row=conn.execute(
            "SELECT id FROM attendance WHERE student_id=? AND classroom_id=? AND DATE(clock_in)=? ORDER BY id LIMIT 1",
            (student_id,class_id,date_text),
        ).fetchone()
        if not row:
            conn.execute(
                """INSERT INTO attendance (student_id,classroom_id,clock_in,clock_out,hours_rendered,status)
                   VALUES (?,?,?,?,8,'Completed')""",
                (student_id,class_id,clock_in,clock_out),
            )
            row=conn.execute(
                "SELECT id FROM attendance WHERE student_id=? AND classroom_id=? AND DATE(clock_in)=? ORDER BY id LIMIT 1",
                (student_id,class_id,date_text),
            ).fetchone()
        if not row: raise RuntimeError("Could not resolve attendance row")
        attendance_id=int(getv(row,"id",0,0))
        assignment_id=assignment_ids[day%len(assignment_ids)]

        log=conn.execute(
            "SELECT id,content FROM logs WHERE attendance_id=? AND student_id=? AND entry_type='daily' ORDER BY id LIMIT 1",
            (attendance_id,student_id),
        ).fetchone()
        if not log:
            conn.execute(
                """INSERT INTO logs
                   (attendance_id,student_id,content,created_at,entry_type,accomplishment,reflection,challenges,related_assignment_id,updated_at)
                   VALUES (?,?,?,?,'daily',?,?,?,?,?)""",
                (
                    attendance_id,student_id,f"{TAG} Daily OJT Logbook for {date_text}.",clock_out,
                    "Completed assigned internship Work, coordinated with the team, and documented the output.",
                    "Improved communication, time management, and technical problem-solving.",
                    "Resolved an implementation blocker after validating the requirement with the supervisor.",
                    assignment_id,clock_out,
                ),
            )
            log=conn.execute(
                "SELECT id,content FROM logs WHERE attendance_id=? AND student_id=? AND entry_type='daily' ORDER BY id LIMIT 1",
                (attendance_id,student_id),
            ).fetchone()
        log_id=None
        log_is_seeded=False
        if log:
            log_id=int(getv(log,"id",0,0))
            log_is_seeded=str(getv(log,"content",1,"") or "").startswith(TAG)
            if not conn.execute("SELECT 1 FROM daily_log_work_links WHERE log_id=? AND assignment_id=? LIMIT 1",(log_id,assignment_id)).fetchone():
                conn.execute("INSERT INTO daily_log_work_links (log_id,assignment_id,sort_order) VALUES (?,?,0)",(log_id,assignment_id))

        pct=round(clamp(score_base+DAY_DELTA[day%len(DAY_DELTA)],60,100),1)
        star=star_for(pct)
        if not conn.execute("SELECT 1 FROM daily_performance_ratings WHERE attendance_id=? LIMIT 1",(attendance_id,)).fetchone():
            conn.execute(
                """INSERT INTO daily_performance_ratings
                   (attendance_id,supervisor_id,star_rating,percentage,comment,rated_at,updated_at)
                   VALUES (?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                (attendance_id,supervisor_id,star,pct,f"{TAG} Supervisor-reviewed Daily Performance for this OJT day."),
            )
        criteria=[
            ("work_quality","Work Quality",clamp(star,1,5),0),
            ("initiative","Initiative",clamp(star+0.1,1,5),1),
            ("professionalism","Professionalism",clamp(star+0.2,1,5),2),
        ]
        for key,name,rating_value,sort_order in criteria:
            if not conn.execute("SELECT 1 FROM daily_performance_rating_items WHERE attendance_id=? AND criterion_key=? LIMIT 1",(attendance_id,key)).fetchone():
                conn.execute(
                    """INSERT INTO daily_performance_rating_items
                       (attendance_id,criterion_key,criterion_name,rating_value,max_value,sort_order)
                       VALUES (?,?,?,?,5.0,?)""",
                    (attendance_id,key,name,round(rating_value,1),sort_order),
                )

        if log_id and log_is_seeded:
            existing_review=conn.execute(
                "SELECT 1 FROM logbook_reviews WHERE log_id=? LIMIT 1",
                (log_id,),
            ).fetchone()
            if not existing_review:
                review_status="approved" if pct>=75.0 else "reviewed"
                review_comment=(
                    f"{TAG} Supervisor review: Daily Performance {pct:.1f}% "
                    f"({label(pct)}). "
                    + (
                        "OJT evidence is complete and approved."
                        if review_status=="approved"
                        else "OJT evidence was reviewed; continue improving the lowest-scoring areas."
                    )
                )
                conn.execute(
                    """INSERT INTO logbook_reviews
                       (log_id,supervisor_id,status,comments,reviewed_at,updated_at)
                       VALUES (?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                    (log_id,supervisor_id,review_status,review_comment),
                )


def ensure_feedback(conn,student_id,supervisor_id,score_base):
    marker=TAG+" Supervisor review"
    if conn.execute("SELECT 1 FROM feedback WHERE student_id=? AND supervisor_id=? AND comment LIKE ? LIMIT 1",(student_id,supervisor_id,marker+"%")).fetchone():
        return
    perf=label(score_base)
    sentiment="Positive" if score_base>=75 else "Neutral"
    competency="Strong Progress" if score_base>=85 else "Developing"
    rec="Maintain the current pace and continue documenting evidence." if score_base>=75 else "Prioritize the lowest-scoring Work items and request a focused supervisor review."
    conn.execute(
        """INSERT INTO feedback
           (student_id,supervisor_id,comment,performance_label,ml_prediction,ml_sentiment,ml_competency,ml_recommendation,ml_svm_prediction,ml_confidence,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
        (student_id,supervisor_id,f"{marker}: {perf.lower()} performance based on reviewed Work and Daily OJT evidence.",perf,perf,sentiment,competency,rec,perf,0.86 if score_base>=75 else 0.79),
    )


def ensure_notifications(conn,student_id,class_id):
    items=[
        ("[Demo] Weekly review available","Your latest internship Work and Daily Performance review is available.","review",0,f"/student/classes/{class_id}/reports"),
        ("[Demo] New Work item assigned","A new internship Work item has been added to your classroom.","task",1,"/student/tasks"),
    ]
    for title,message,kind,is_read,link in items:
        existing=conn.execute(
            "SELECT id,link_url FROM notifications WHERE user_id=? AND title=? LIMIT 1",
            (student_id,title),
        ).fetchone()
        if existing:
            notification_id=int(getv(existing,"id",0,0))
            current_link=str(getv(existing,"link_url",1,"") or "")
            if current_link!=link:
                conn.execute(
                    "UPDATE notifications SET link_url=? WHERE id=? AND user_id=?",
                    (link,notification_id,student_id),
                )
            continue
        conn.execute(
            """INSERT INTO notifications (user_id,title,message,notification_type,is_read,link_url,created_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (student_id,title,message,kind,is_read,link),
        )


def ensure_history(conn,student_id,supervisor_id):
    action=TAG+" profile populated"
    if not conn.execute("SELECT 1 FROM profile_history WHERE student_id=? AND action=? LIMIT 1",(student_id,action)).fetchone():
        conn.execute("INSERT INTO profile_history (student_id,changed_by,action,created_at) VALUES (?,?,?,CURRENT_TIMESTAMP)",(student_id,supervisor_id,action))


def ensure_evaluation(conn,class_id,student_id,supervisor_id,score_base,slot):
    row=conn.execute("SELECT id FROM ojt_evaluations WHERE classroom_id=? AND student_id=? LIMIT 1",(class_id,student_id)).fetchone()
    if not row:
        status="draft" if slot%5==0 else "submitted"
        submitted=None if status=="draft" else datetime.now()
        conn.execute(
            """INSERT INTO ojt_evaluations
               (classroom_id,student_id,supervisor_id,status,overall_score,remarks,created_at,updated_at,submitted_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,?)""",
            (class_id,student_id,supervisor_id,status,round(score_base,1),TAG+" Manual sample Official OJT Evaluation for demo/report population.",submitted),
        )
        row=conn.execute("SELECT id FROM ojt_evaluations WHERE classroom_id=? AND student_id=? LIMIT 1",(class_id,student_id)).fetchone()
    if not row:return
    evaluation_id=int(getv(row,"id",0,0))
    count=conn.execute("SELECT COUNT(*) AS total FROM ojt_evaluation_items WHERE evaluation_id=?",(evaluation_id,)).fetchone()
    if int(getv(count,"total",0,0) or 0)>0:return
    star=star_for(score_base)
    items=[
        ("Work Quality",clamp(star,1,5),35.0,"Consistently applies supervisor feedback to assigned outputs."),
        ("Initiative and Problem Solving",clamp(star+0.1,1,5),35.0,"Shows initiative in resolving blockers and documenting decisions."),
        ("Professionalism and Communication",clamp(star+0.2,1,5),30.0,"Communicates progress clearly and follows workplace expectations."),
    ]
    for order,(criterion,rating,weight,comments) in enumerate(items):
        conn.execute(
            """INSERT INTO ojt_evaluation_items
               (evaluation_id,criterion_name,rating_value,max_value,weight,comments,sort_order)
               VALUES (?,?,?,5.0,?,?,?)""",
            (evaluation_id,criterion,round(rating,1),weight,comments,order),
        )


def populate_classroom(conn,classroom,password_hash):
    class_id=int(getv(classroom,"id",0,0))
    supervisor_id=int(getv(classroom,"supervisor_id",1,0))
    class_name=str(getv(classroom,"name",2,f"Classroom {class_id}") or f"Classroom {class_id}")
    supervisor_name=str(getv(classroom,"supervisor_username",4,"Supervisor") or "Supervisor")
    supervisor_email=str(getv(classroom,"supervisor_email",5,"") or "")
    company=company_for(conn,class_id,class_name)

    needed=max(0,TARGET_STUDENTS-roster_count(conn,class_id))
    for slot in range(1,TARGET_STUDENTS+1):
        if needed<=0:break
        username=f"seed_c{class_id}_s{slot:02d}"
        existing=find_user(conn,username)
        if existing:
            student_id=int(getv(existing,"id",0,0))
            if not conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id=? AND student_id=? LIMIT 1",(class_id,student_id)).fetchone():
                enroll(conn,class_id,student_id); needed-=1
            continue
        create_seed_user(conn,class_id,slot,password_hash); needed-=1

    roster=conn.execute(
        """SELECT u.id,u.username,u.email
           FROM classroom_students cs JOIN users u ON u.id=cs.student_id
           WHERE cs.classroom_id=? AND u.role='student'
           ORDER BY cs.joined_at,u.id""",
        (class_id,),
    ).fetchall()
    if not roster: raise RuntimeError(f"No students found in classroom {class_id}")

    ensure_posts(conn,class_id,supervisor_id)
    assignment_ids=ensure_work_items(conn,class_id,supervisor_id)

    for slot,row in enumerate(roster,start=1):
        student_id=int(getv(row,"id",0,0))
        backfill_student_account(conn,student_id,class_id)
        backfill_profile(conn,student_id,class_id,slot)
        ensure_assignment_link(conn,student_id,supervisor_id)
        ensure_internship(conn,student_id,supervisor_id,supervisor_name,supervisor_email,company,slot)
        score_base=base_score(slot)
        ensure_work_scores(conn,student_id,assignment_ids,score_base)
        ensure_tasks(conn,student_id,supervisor_id)
        ensure_attendance_logbook(conn,student_id,class_id,supervisor_id,assignment_ids,score_base)
        ensure_feedback(conn,student_id,supervisor_id,score_base)
        ensure_notifications(conn,student_id,class_id)
        ensure_history(conn,student_id,supervisor_id)
        ensure_evaluation(conn,class_id,student_id,supervisor_id,score_base,slot)

    return class_id,class_name,roster_count(conn,class_id),len(roster)


def schema_check(conn):
    required=[
        "users","student_profiles","classrooms","classroom_students","classroom_posts",
        "classroom_assignments","classroom_submissions","classwork_scores","student_assignments",
        "internships","attendance","logs","daily_log_work_links","daily_performance_ratings",
        "daily_performance_rating_items","logbook_reviews","feedback","tasks","notifications","profile_history",
        "ojt_evaluations","ojt_evaluation_items",
    ]
    missing=[name for name in required if not table_exists(conn,name)]
    print("Schema availability:")
    for name in required: print(f"  - {name}: {'OK' if name not in missing else 'MISSING'}")
    required_columns={
        "attendance":{"classroom_id"},
        "logs":{"entry_type","accomplishment","reflection","challenges","related_assignment_id","updated_at"},
    }
    missing_cols=[]
    for name,expected in required_columns.items():
        absent=sorted(expected-columns(conn,name))
        if absent:
            missing_cols.append((name,absent))
            print(f"  - {name} missing columns: {', '.join(absent)}")
    return missing,missing_cols


def main():
    conn=get_db_connection()
    try:
        classrooms=active_classrooms(conn)
        print("Nexora demo seed mode: "+("APPLY" if APPLY else "DRY RUN"))
        print(f"Active classrooms found: {len(classrooms)}")
        for classroom in classrooms:
            class_id=int(getv(classroom,"id",0,0))
            name=str(getv(classroom,"name",2,"") or "")
            count=roster_count(conn,class_id)
            print(f"  - {class_id}: {name!r}, roster={count}, target={TARGET_STUDENTS}, add={max(0,TARGET_STUDENTS-count)}")

        missing,missing_cols=schema_check(conn)
        if len(classrooms)!=TARGET_CLASSROOMS:
            raise RuntimeError(f"Expected exactly {TARGET_CLASSROOMS} active classrooms; found {len(classrooms)}.")
        if missing or missing_cols:
            raise RuntimeError("Existing Nexora feature schema is incomplete. No schema changes were attempted.")
        if not APPLY:
            print("DRY RUN complete. No rows changed.")
            return 0
        if len(PASSWORD)<12:
            raise RuntimeError("NEXORA_DEMO_PASSWORD must contain at least 12 characters.")

        password_hash=hash_password(PASSWORD)
        summaries=[populate_classroom(conn,classroom,password_hash) for classroom in classrooms]
        conn.commit()
        print("Seed applied successfully.")
        for class_id,name,roster,populated_count in summaries:
            print(f"  - {class_id}: {name!r}, roster={roster}, student accounts populated={populated_count}")
        return 0
    except Exception as error:
        try: conn.rollback()
        except Exception: pass
        print("Nexora demo seed FAILED: "+str(error),file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__=="__main__":
    raise SystemExit(main())
