import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR=Path(__file__).resolve().parent.parent; load_dotenv(BASE_DIR/".env")
from flask import Flask,send_from_directory,session,redirect,url_for,flash,request
from app.Http.Middleware.security import login_required
from app.Http.Controllers.auth import auth
from app.Http.Controllers.password import password
from app.Http.Controllers.student import student
from app.Http.Controllers.daily_logbook import daily_logbook
from app.Http.Controllers.logbook_review import logbook_review
from app.Http.Controllers.daily_performance_history import daily_performance_history
from app.Http.Controllers.intern_profile import intern_profile
from app.Http.Controllers.ojt_evaluation import ojt_evaluation
from app.Http.Controllers.needs_attention import needs_attention
from app.Http.Controllers.supervisor import supervisor
from app.Http.Controllers.supervisor_documents import supervisor_documents
from app.Http.Controllers.admin import admin
from app.Http.Controllers.admin_assigned_interns import admin_assigned_interns
from app.Http.Controllers.classroom import classroom
from app.Http.Controllers.internship_classroom import internship_classroom
from app.Http.Controllers.classwork import classwork
from app.Http.Controllers.student_classwork import student_classwork
from app.Http.Controllers.student_gradebook import student_gradebook
from app.Http.Controllers.student_classmates import student_classmates
from app.Http.Controllers.classwork_submissions import classwork_submissions
from app.Http.Controllers.classwork_grading import classwork_grading
from app.Http.Controllers.classwork_scores import classwork_scores
from app.Http.Controllers.classwork_gradebook import classwork_gradebook
from app.Http.Controllers.classwork_gradebook_export import classwork_gradebook_export
from app.Http.Controllers.classwork_ml_insights import classwork_ml_insights
from app.Http.Controllers.performance_reports import performance_reports
from app.Http.Controllers.admin_classrooms import admin_classrooms
from app.Http.Controllers.admin_reports_overview import admin_reports_overview
from app.Http.Controllers.admin_trash import admin_trash
from app.Http.Controllers.account_appeals import account_appeals
from app.Http.Controllers.supervisor_profile_photo import supervisor_profile_photo
from app.Http.Controllers.assistant import assistant_bp
from app.Http.Controllers.notifications import notifications_bp
from app.Http.Controllers.messages import messages
from scripts.init_db import initialize_database
from app.Models.db import get_db_connection,using_postgres
from app.Services.classroom_service import ensure_classroom_schema
from app.Services.classroom_post_service import get_classroom_announcements
from app.Services.classwork_submission_service import ensure_classwork_submission_schema
from app.Services.classwork_score_schema import ensure_classwork_score_schema
from app.Services.attendance_service import ensure_attendance_schema,get_ojt_progress
from app.Services.logbook_service import ensure_logbook_schema,get_daily_logbook_context,get_session_daily_log
from app.Services.logbook_photo_service import ensure_logbook_photo_schema,get_logbook_photos
from app.Services.logbook_review_service import ensure_logbook_review_schema
from app.Services.performance_rating_service import ensure_daily_performance_rating_schema
from app.Services.ojt_evaluation_service import ensure_ojt_evaluation_schema
from app.Services.internship_schedule_service import ensure_internship_schedule_schema,get_student_schedule_state
from app.Services.notification_service import get_user_notifications,get_recent_notifications,get_unread_count
from app.Services.supervisor_profile_service import ensure_supervisor_profile_schema
from app.Services.account_approval_service import (
    cleanup_legacy_rejected_accounts,
    start_account_approval_worker,
)
from app.Services.account_appeal_service import (
    ensure_account_appeal_schema,
    get_submitted_appeal_count,
    start_account_appeal_worker,
)
app=Flask(__name__,template_folder=str(BASE_DIR/"resources"/"views"),static_folder=str(BASE_DIR/"resources"/"assets"),static_url_path="/static")
app.jinja_env.globals["get_ojt_progress"]=get_ojt_progress
app.jinja_env.globals["get_daily_logbook_context"]=get_daily_logbook_context
app.jinja_env.globals["get_session_daily_log"]=get_session_daily_log
app.jinja_env.globals["get_logbook_photos"]=get_logbook_photos
app.jinja_env.globals["get_classroom_announcements"]=get_classroom_announcements
app.jinja_env.globals["get_student_schedule_state"]=get_student_schedule_state
_secret=os.environ.get("SECRET_KEY")
if not _secret:
 if os.environ.get("FLASK_ENV")=="production" or os.environ.get("NEXORA_ENV")=="production": raise RuntimeError("SECRET_KEY must be set in production")
 _secret="dev-secret-key-change-me-not-for-production"
app.secret_key=_secret; app.config.update(SECRET_KEY=_secret,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",PERMANENT_SESSION_LIFETIME=timedelta(days=7),SESSION_REFRESH_EACH_REQUEST=False,MAX_CONTENT_LENGTH=45*1024*1024); app.config["SESSION_COOKIE_SECURE"]=os.environ.get("SESSION_COOKIE_SECURE","").lower() in ("1","true","yes") or os.environ.get("FLASK_ENV")=="production" or os.environ.get("NEXORA_ENV")=="production"; app.config["WTF_CSRF_ENABLED"]=True; app.config["WTF_CSRF_TIME_LIMIT"]=None; _debug=os.environ.get("FLASK_DEBUG",os.environ.get("NEXORA_DEBUG","0")); app.debug=_debug.lower() in ("1","true","yes")
try:
 from flask_wtf.csrf import CSRFProtect
 csrf=CSRFProtect(app)
except ImportError as exc:
 if app.config.get("WTF_CSRF_ENABLED"): raise RuntimeError("Flask-WTF is required for CSRF protection") from exc
 csrf=None
@app.after_request
def _security(response):
 response.headers["X-Content-Type-Options"]="nosniff"; response.headers["X-Frame-Options"]="DENY"; response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"; response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; img-src 'self' data: blob: https:; font-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'"; return response
@app.errorhandler(413)
def request_entity_too_large(error):
 if request.path=="/student/daily-log/save":
  flash("Photo upload is too large. Daily OJT evidence supports up to 5 photos at 8 MB each.","danger")
  return redirect(url_for("student.logbook",daily_entry_error="request_too_large"))
 if request.path.startswith("/student/daily-log/"):
  flash("Photo upload is too large. Daily OJT evidence supports up to 5 photos at 8 MB each.","danger")
  return redirect(url_for("student.logbook"))
 return "Request Entity Too Large",413
UPLOAD_FOLDER=BASE_DIR/"storage"/"uploads"; UPLOAD_FOLDER.mkdir(parents=True,exist_ok=True); app.config["UPLOAD_FOLDER"]=str(UPLOAD_FOLDER); PROFILE_UPLOAD_FOLDER=UPLOAD_FOLDER/"profile_pictures"; PROFILE_UPLOAD_FOLDER.mkdir(parents=True,exist_ok=True); app.config["PROFILE_UPLOAD_FOLDER"]=str(PROFILE_UPLOAD_FOLDER)
def _is_registered_document_upload(filename):
 candidate=(UPLOAD_FOLDER/filename).resolve()
 conn=get_db_connection()
 try:
  rows=conn.execute("SELECT filepath FROM documents WHERE filepath IS NOT NULL").fetchall()
 except Exception:
  return True
 finally:
  conn.close()
 for row in rows:
  try:
   stored=row[0]
   if stored and Path(stored).resolve()==candidate:return True
  except Exception:
   continue
 return False
@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    user_id = session.get("user_id")
    role = session.get("role")
    conn = get_db_connection()
    authorized = False
    try:
        is_doc = _is_registered_document_upload(filename)
        if is_doc:
            if role == "admin": authorized = True
            else: return "Direct document access is not allowed.", 403
        else:
            if filename.startswith("profile_pictures/"):
                if role == "admin": authorized = True
            elif filename.startswith("classwork/"):
                parts = filename.split('/')
                if len(parts) >= 3 and parts[0] == 'classwork':
                    class_id_str, assignment_id_str, *resource_parts = parts[1:]
                    try:
                        class_id = int(class_id_str)
                        if role == "admin": authorized = True
                        elif role == "student":
                            if conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id = ? AND student_id = ?", (class_id, user_id)).fetchone(): authorized = True
                        elif role == "supervisor":
                            if conn.execute("SELECT 1 FROM classrooms WHERE id = ? AND supervisor_id = ?", (class_id, user_id)).fetchone(): authorized = True
                    except ValueError: pass
        if not authorized:return "Access denied.",403
    finally:conn.close()
    return send_from_directory(str(UPLOAD_FOLDER),filename)
@app.route("/uploads/profile_pictures/<filename>")
@login_required
def profile_picture(filename): return send_from_directory(app.config["PROFILE_UPLOAD_FOLDER"],filename)
@app.route("/profile-picture/<int:user_id>")
@login_required
def user_profile_picture(user_id):
 conn=get_db_connection()
 try:row=conn.execute("SELECT profile_picture FROM student_profiles WHERE user_id=?",(user_id,)).fetchone(); filename=row[0] if row else None
 finally:conn.close()
 return send_from_directory(str(PROFILE_UPLOAD_FOLDER if filename else BASE_DIR/"resources"/"assets"/"images"),filename or "default_profile.png")
@app.route("/favicon.ico")
def favicon():
 role=session.get("role"); filename={"student":"nexora_logo_student.png","supervisor":"nexora_logo_supervisor.png","admin":"nexora_logo_admin.png"}.get(role,"nexora_logo_supervisor.png")
 return send_from_directory(str(BASE_DIR/"resources"/"assets"/"images"),filename,mimetype="image/png")
@app.route("/health")
def health():return {"status":"ok"},200

def ensure_session_schema():
 conn=get_db_connection();cur=conn.cursor()
 try:
  if using_postgres():
   cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0");cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture TEXT")
  else:
   cols=[r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
   if "session_version" not in cols:cur.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
   if "profile_picture" not in cols:cur.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT")
  conn.commit()
 except Exception as exc:conn.rollback();print("session/profile schema skipped:",exc)
 finally:cur.close();conn.close()
def repair_missing_student_profiles():
 conn=get_db_connection();cur=conn.cursor()
 try:
  sql=("INSERT INTO student_profiles (user_id,profile_completed) SELECT u.id,0 FROM users u WHERE u.role='student' AND NOT EXISTS (SELECT 1 FROM student_profiles sp WHERE sp.user_id=u.id) ON CONFLICT (user_id) DO NOTHING" if using_postgres() else "INSERT OR IGNORE INTO student_profiles (user_id,profile_completed) SELECT u.id,0 FROM users u WHERE u.role='student' AND NOT EXISTS (SELECT 1 FROM student_profiles sp WHERE sp.user_id=u.id)");cur.execute(sql);conn.commit()
 except Exception as exc:conn.rollback();print("student profile repair skipped:",exc)
 finally:cur.close();conn.close()
initialize_database();ensure_supervisor_profile_schema();ensure_classroom_schema();ensure_classwork_submission_schema();ensure_classwork_score_schema();ensure_attendance_schema();ensure_logbook_schema();ensure_logbook_photo_schema();ensure_logbook_review_schema();ensure_daily_performance_rating_schema();ensure_ojt_evaluation_schema();ensure_internship_schedule_schema();ensure_session_schema();repair_missing_student_profiles();ensure_account_appeal_schema()
for bp in (auth,password,student,daily_logbook,logbook_review,daily_performance_history,intern_profile,ojt_evaluation,needs_attention,student_classwork,student_gradebook,student_classmates,supervisor,supervisor_documents,admin,admin_assigned_interns,classroom,internship_classroom,classwork,classwork_submissions,classwork_grading,classwork_scores,classwork_gradebook,classwork_gradebook_export,classwork_ml_insights,performance_reports,admin_classrooms,admin_reports_overview,admin_trash,account_appeals,supervisor_profile_photo,assistant_bp,notifications_bp,messages):app.register_blueprint(bp)
try:
 cleaned_rejected_accounts=cleanup_legacy_rejected_accounts()
 if cleaned_rejected_accounts:
  app.logger.info("Removed %s legacy rejected account(s).",cleaned_rejected_accounts)
except Exception as exc:
 app.logger.warning("Could not clean legacy rejected accounts: %s",exc)
start_account_approval_worker(app)
start_account_appeal_worker(app)
@app.before_request
def enforce_single_supervisor_session():
 if session.get("role")!="supervisor" or not session.get("user_id") or request.path in ("/login","/logout","/signup","/") or request.path.startswith("/static/"):return None
 conn=get_db_connection()
 try:row=conn.execute("SELECT session_version FROM users WHERE id=?",(session["user_id"],)).fetchone()
 finally:conn.close()
 current=row[0] if row else None
 if current is not None and session.get("session_version")!=int(current):session.clear();session["login_error"]="You were signed out because this supervisor account logged in on another device.";return redirect(url_for("auth.login"))
@app.context_processor
def inject_notifications():
 defaults={"notifications":[],"recent_notifications":[],"unread_count":0,"sidebar_profile":None,"supervisor_classroom_pending_count":0,"supervisor_evaluation_pending_count":0,"supervisor_class_pending_counts":{},"supervisor_class_card_stats":{},"admin_pending_approval_count":0,"admin_appeal_count":0}
 if "user_id" not in session:return defaults
 uid=session["user_id"];sidebar=None;supervisor_class_pending_counts={};supervisor_class_card_stats={};supervisor_classroom_pending_count=0;supervisor_evaluation_pending_count=0;admin_pending_approval_count=0;admin_appeal_count=0
 try:
  conn=get_db_connection()
  try:
   user=conn.execute("SELECT id,username,email,role,profile_picture FROM users WHERE id=?",(uid,)).fetchone()
   if user:
    sidebar={"id":user["id"],"username":user["username"],"email":user["email"],"role":user["role"],"profile_picture":user["profile_picture"]}
    if user["role"]=="student":
     p=conn.execute("SELECT first_name,last_name,profile_picture FROM student_profiles WHERE user_id=?",(uid,)).fetchone()
     if p:sidebar.update({"first_name":p["first_name"],"last_name":p["last_name"],"profile_picture":p["profile_picture"]})
    elif user["role"]=="supervisor":
     p=conn.execute("SELECT first_name,last_name FROM supervisor_profiles WHERE user_id=?",(uid,)).fetchone()
     if p:sidebar.update({"first_name":p["first_name"],"last_name":p["last_name"]})
     pending_rows=conn.execute("""
      SELECT c.id AS classroom_id,
             (SELECT COUNT(*) FROM logs l JOIN attendance a ON a.id=l.attendance_id LEFT JOIN logbook_reviews r ON r.log_id=l.id WHERE l.entry_type='daily' AND a.classroom_id=c.id AND COALESCE(a.status,'Open')<>'Open' AND COALESCE(r.status,'pending')='pending') AS pending_logbooks,
             (SELECT COUNT(*) FROM classwork_submissions s JOIN classroom_assignments ca ON ca.id=s.assignment_id WHERE ca.classroom_id=c.id AND COALESCE(s.status,'submitted')='submitted' AND s.grade IS NULL) AS pending_work
      FROM classrooms c WHERE c.supervisor_id=? AND COALESCE(c.archived,0)=0
     """,(uid,)).fetchall()
     for pending_row in pending_rows:
      class_id=int(pending_row["classroom_id"] if "classroom_id" in pending_row.keys() else pending_row[0]);logbook_pending=int(pending_row["pending_logbooks"] if "pending_logbooks" in pending_row.keys() else pending_row[1] or 0);work_pending=int(pending_row["pending_work"] if "pending_work" in pending_row.keys() else pending_row[2] or 0);total_pending=logbook_pending+work_pending
      supervisor_class_pending_counts[class_id]={"logbook":logbook_pending,"work":work_pending,"total":total_pending};supervisor_classroom_pending_count+=total_pending
     card_rows=conn.execute("""
      SELECT c.id AS classroom_id,COALESCE(c.archived,0) AS archived,
             COALESCE(cid.program,'') AS program,COALESCE(cid.required_hours,0) AS required_hours,
             COALESCE(cid.required_days,0) AS required_days,COALESCE(cid.hours_per_day,0) AS hours_per_day,
             COALESCE(cid.attendance_days,'') AS attendance_days,COALESCE(cid.shift_start_time,'') AS shift_start_time,
             COALESCE(cid.shift_end_time,'') AS shift_end_time,
             (SELECT COUNT(*) FROM classroom_students cs WHERE cs.classroom_id=c.id) AS student_count,
             (SELECT COUNT(*) FROM ojt_evaluations e WHERE e.classroom_id=c.id AND e.supervisor_id=c.supervisor_id AND LOWER(COALESCE(e.status,''))='submitted') AS submitted_evaluations
      FROM classrooms c LEFT JOIN classroom_internship_details cid ON cid.classroom_id=c.id WHERE c.supervisor_id=?
     """,(uid,)).fetchall()
     for card_row in card_rows:
      class_id=int(card_row["classroom_id"] if "classroom_id" in card_row.keys() else card_row[0]);archived=bool(card_row["archived"] if "archived" in card_row.keys() else card_row[1]);program=(card_row["program"] if "program" in card_row.keys() else card_row[2]) or "";required_hours=float((card_row["required_hours"] if "required_hours" in card_row.keys() else card_row[3]) or 0);required_days=int((card_row["required_days"] if "required_days" in card_row.keys() else card_row[4]) or 0);hours_per_day=int((card_row["hours_per_day"] if "hours_per_day" in card_row.keys() else card_row[5]) or 0);attendance_days=(card_row["attendance_days"] if "attendance_days" in card_row.keys() else card_row[6]) or "";shift_start_time=(card_row["shift_start_time"] if "shift_start_time" in card_row.keys() else card_row[7]) or "";shift_end_time=(card_row["shift_end_time"] if "shift_end_time" in card_row.keys() else card_row[8]) or "";student_count=int((card_row["student_count"] if "student_count" in card_row.keys() else card_row[9]) or 0);submitted_evaluations=int((card_row["submitted_evaluations"] if "submitted_evaluations" in card_row.keys() else card_row[10]) or 0)
      progress_rows=conn.execute("""
       SELECT cs.student_id,COALESCE(SUM(CASE WHEN a.status='Completed' THEN COALESCE(a.hours_rendered,0) ELSE 0 END),0) AS rendered_hours,
              COUNT(DISTINCT CASE WHEN a.status='Completed' THEN DATE(a.clock_in) END) AS completed_days
       FROM classroom_students cs LEFT JOIN attendance a ON a.student_id=cs.student_id AND a.classroom_id=cs.classroom_id
       WHERE cs.classroom_id=? GROUP BY cs.student_id
      """,(class_id,)).fetchall()
      progress_total=0.0;completed_interns=0;minimum_completed_days=required_days if student_count and required_days>0 else 0;days_left=required_days if student_count==0 and required_days>0 else 0
      for progress_row in progress_rows:
       rendered_hours=float((progress_row["rendered_hours"] if "rendered_hours" in progress_row.keys() else progress_row[1]) or 0);completed_days=int((progress_row["completed_days"] if "completed_days" in progress_row.keys() else progress_row[2]) or 0);ratios=[]
       if required_hours>0:ratios.append(min(1.0,max(0.0,rendered_hours/required_hours)))
       if required_days>0:ratios.append(min(1.0,max(0.0,completed_days/required_days)))
       progress_total+=min(ratios) if ratios else 0.0
       if required_days>0:
        minimum_completed_days=min(minimum_completed_days,completed_days);days_left=max(days_left,max(0,required_days-completed_days))
        if completed_days>=required_days:completed_interns+=1
      progress_percent=int(round((progress_total/student_count)*100)) if student_count else 0;days_progress_percent=int(round((minimum_completed_days/required_days)*100)) if student_count and required_days>0 else 0;pending_evaluations=max(0,student_count-submitted_evaluations);evaluation_ready=student_count>0 and required_days>0 and days_left==0
      if evaluation_ready and not archived:supervisor_evaluation_pending_count+=pending_evaluations
      supervisor_class_card_stats[class_id]={"program":program,"required_hours":required_hours,"required_days":required_days,"hours_per_day":hours_per_day,"attendance_days":attendance_days,"shift_start_time":shift_start_time,"shift_end_time":shift_end_time,"progress_percent":max(0,min(100,progress_percent)),"days_progress_percent":max(0,min(100,days_progress_percent)),"minimum_completed_days":minimum_completed_days,"days_left":days_left,"completed_interns":completed_interns,"student_count":student_count,"submitted_evaluations":submitted_evaluations,"pending_evaluations":pending_evaluations,"evaluation_ready":evaluation_ready}
    elif user["role"]=="admin":
     pending_approval_row=conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('pending_student','pending_supervisor')").fetchone()
     if pending_approval_row:admin_pending_approval_count=int(pending_approval_row[0] or 0)
     admin_appeal_count=get_submitted_appeal_count()
  finally:conn.close()
  return {"notifications":get_user_notifications(uid,limit=20),"recent_notifications":get_recent_notifications(uid,days=7,limit=10),"unread_count":get_unread_count(uid),"sidebar_profile":sidebar,"supervisor_classroom_pending_count":supervisor_classroom_pending_count,"supervisor_evaluation_pending_count":supervisor_evaluation_pending_count,"supervisor_class_pending_counts":supervisor_class_pending_counts,"supervisor_class_card_stats":supervisor_class_card_stats,"admin_pending_approval_count":admin_pending_approval_count,"admin_appeal_count":admin_appeal_count}
 except Exception as exc:print("inject_notifications failed:",exc);defaults["sidebar_profile"]=sidebar;return defaults
if __name__=="__main__":app.run(debug=app.debug)