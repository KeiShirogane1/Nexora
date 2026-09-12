import os
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
from app.Http.Controllers.supervisor_profile_photo import supervisor_profile_photo
from app.Http.Controllers.notifications import notifications_bp
from scripts.init_db import initialize_database
from app.Models.db import get_db_connection,using_postgres
from app.Services.classroom_service import ensure_classroom_schema
from app.Services.classwork_submission_service import ensure_classwork_submission_schema
from app.Services.classwork_score_schema import ensure_classwork_score_schema
from app.Services.attendance_service import ensure_attendance_schema,get_ojt_progress
from app.Services.logbook_service import ensure_logbook_schema,get_daily_logbook_context,get_session_daily_log
from app.Services.logbook_photo_service import ensure_logbook_photo_schema,get_logbook_photos
from app.Services.logbook_review_service import ensure_logbook_review_schema
from app.Services.performance_rating_service import ensure_daily_performance_rating_schema
from app.Services.ojt_evaluation_service import ensure_ojt_evaluation_schema
from app.Services.notification_service import get_user_notifications,get_recent_notifications,get_unread_count
app=Flask(__name__,template_folder=str(BASE_DIR/"resources"/"views"),static_folder=str(BASE_DIR/"resources"/"assets"),static_url_path="/static")
app.jinja_env.globals["get_ojt_progress"]=get_ojt_progress
app.jinja_env.globals["get_daily_logbook_context"]=get_daily_logbook_context
app.jinja_env.globals["get_session_daily_log"]=get_session_daily_log
app.jinja_env.globals["get_logbook_photos"]=get_logbook_photos
_secret=os.environ.get("SECRET_KEY")
if not _secret:
 if os.environ.get("FLASK_ENV")=="production" or os.environ.get("NEXORA_ENV")=="production": raise RuntimeError("SECRET_KEY must be set in production")
 _secret="dev-secret-key-change-me-not-for-production"
app.secret_key=_secret; app.config.update(SECRET_KEY=_secret,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",MAX_CONTENT_LENGTH=45*1024*1024); app.config["SESSION_COOKIE_SECURE"]=os.environ.get("SESSION_COOKIE_SECURE","").lower() in ("1","true","yes") or os.environ.get("FLASK_ENV")=="production" or os.environ.get("NEXORA_ENV")=="production"; app.config["WTF_CSRF_ENABLED"]=True; app.config["WTF_CSRF_TIME_LIMIT"]=None; _debug=os.environ.get("FLASK_DEBUG",os.environ.get("NEXORA_DEBUG","0")); app.debug=_debug.lower() in ("1","true","yes")
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
 if _is_registered_document_upload(filename):return "Direct document access is not allowed.",403
 return send_from_directory(str(UPLOAD_FOLDER),filename)
@app.route("/uploads/profile_pictures/<filename>")
@login_required
def profile_picture(filename): return send_from_directory(app.config["PROFILE_UPLOAD_FOLDER"],filename)
@app.route("/profile-picture/<int:user_id>")
@login_required
def user_profile_picture(user_id):
 conn=get_db_connection()
 try:
  row=conn.execute("SELECT profile_picture FROM student_profiles WHERE user_id=?",(user_id,)).fetchone(); filename=row[0] if row else None
 finally: conn.close()
 return send_from_directory(str(PROFILE_UPLOAD_FOLDER if filename else BASE_DIR/"resources"/"assets"/"images"),filename or "default_profile.png")
@app.route("/favicon.ico")
def favicon(): return send_from_directory(str(BASE_DIR/"resources"/"assets"/"images"),"Nexora.png",mimetype="image/png")
@app.route("/health")
def health(): return {"status":"ok"},200

def ensure_session_schema():
 conn=get_db_connection(); cur=conn.cursor()
 try:
  if using_postgres():
   cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0"); cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture TEXT")
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
initialize_database();ensure_classroom_schema();ensure_classwork_submission_schema();ensure_classwork_score_schema();ensure_attendance_schema();ensure_logbook_schema();ensure_logbook_photo_schema();ensure_logbook_review_schema();ensure_daily_performance_rating_schema();ensure_ojt_evaluation_schema();ensure_session_schema();repair_missing_student_profiles()
for bp in (auth,password,student,daily_logbook,logbook_review,daily_performance_history,intern_profile,ojt_evaluation,needs_attention,student_classwork,student_gradebook,student_classmates,supervisor,supervisor_documents,admin,admin_assigned_interns,classroom,internship_classroom,classwork,classwork_submissions,classwork_grading,classwork_scores,classwork_gradebook,classwork_gradebook_export,classwork_ml_insights,performance_reports,admin_classrooms,admin_reports_overview,admin_trash,supervisor_profile_photo,notifications_bp):app.register_blueprint(bp)
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
 if "user_id" not in session:return {"notifications":[],"recent_notifications":[],"unread_count":0,"sidebar_profile":None}
 uid=session["user_id"];sidebar=None
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
  finally:conn.close()
  return {"notifications":get_user_notifications(uid,limit=20),"recent_notifications":get_recent_notifications(uid,days=7,limit=10),"unread_count":get_unread_count(uid),"sidebar_profile":sidebar}
 except Exception as exc:print("inject_notifications failed:",exc);return {"notifications":[],"recent_notifications":[],"unread_count":0,"sidebar_profile":sidebar}
if __name__=="__main__":app.run(debug=app.debug)
