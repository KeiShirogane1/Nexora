import os
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR=Path(__file__).resolve().parent.parent; load_dotenv(BASE_DIR/".env")
from flask import Flask,send_from_directory,session
from app.Http.Controllers.auth import auth
from app.Http.Controllers.password import password
from app.Http.Controllers.student import student
from app.Http.Controllers.supervisor import supervisor
from app.Http.Controllers.admin import admin
from app.Http.Controllers.classroom import classroom
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
from app.Http.Controllers.admin_reports_overview import admin_reports_overview
from app.Http.Controllers.notifications import notifications_bp
from scripts.init_db import initialize_database
from app.Models.db import get_db_connection,using_postgres
from app.Services.classroom_service import ensure_classroom_schema
from app.Services.classwork_submission_service import ensure_classwork_submission_schema
from app.Services.classwork_score_schema import ensure_classwork_score_schema
from app.Services.notification_service import get_user_notifications,get_recent_notifications,get_unread_count

app=Flask(__name__,template_folder=str(BASE_DIR/"resources"/"views"),static_folder=str(BASE_DIR/"resources"/"assets"),static_url_path="/static")
_secret=os.environ.get("SECRET_KEY")
if not _secret:
    if os.environ.get("FLASK_ENV")=="production" or os.environ.get("NEXORA_ENV")=="production": raise RuntimeError("SECRET_KEY must be set in production")
    _secret="dev-secret-key-change-me-not-for-production"
app.secret_key=_secret; app.config.update(SECRET_KEY=_secret,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",MAX_CONTENT_LENGTH=5*1024*1024)
app.config["SESSION_COOKIE_SECURE"]=os.environ.get("SESSION_COOKIE_SECURE","").lower() in ("1","true","yes") or os.environ.get("FLASK_ENV")=="production" or os.environ.get("NEXORA_ENV")=="production"
_debug=os.environ.get("FLASK_DEBUG",os.environ.get("NEXORA_DEBUG","0")); app.debug=_debug.lower() in ("1","true","yes"); app.config["WTF_CSRF_ENABLED"]=True; app.config["WTF_CSRF_TIME_LIMIT"]=None
try:
 from flask_wtf.csrf import CSRFProtect
 csrf=CSRFProtect(app)
except ImportError as exc:
 if app.config.get("WTF_CSRF_ENABLED"): raise RuntimeError("Flask-WTF is required for CSRF protection") from exc
 csrf=None
@app.after_request
def _security(response):
 response.headers["X-Content-Type-Options"]="nosniff"; response.headers["X-Frame-Options"]="DENY"; response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"; response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; img-src 'self' data: blob: https:; font-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'"
 if app.config.get("SESSION_COOKIE_SECURE"): response.headers["Strict-Transport-Security"]="max-age=31536000; includeSubDomains"
 return response
UPLOAD_FOLDER=BASE_DIR/"storage"/"uploads"; UPLOAD_FOLDER.mkdir(parents=True,exist_ok=True); app.config["UPLOAD_FOLDER"]=str(UPLOAD_FOLDER)
PROFILE_UPLOAD_FOLDER=UPLOAD_FOLDER/"profile_pictures"; PROFILE_UPLOAD_FOLDER.mkdir(parents=True,exist_ok=True); app.config["PROFILE_UPLOAD_FOLDER"]=str(PROFILE_UPLOAD_FOLDER)
@app.route("/uploads/<path:filename>")
def uploaded_file(filename): return send_from_directory(str(UPLOAD_FOLDER),filename)
@app.route("/uploads/profile_pictures/<filename>")
def profile_picture(filename): return send_from_directory(app.config["PROFILE_UPLOAD_FOLDER"],filename)
@app.route("/profile-picture/<int:user_id>")
def user_profile_picture(user_id):
 conn=get_db_connection()
 try: row=conn.execute("SELECT profile_picture FROM student_profiles WHERE user_id=?",(user_id,)).fetchone(); filename=row[0] if row else None
 finally: conn.close()
 if filename: return send_from_directory(str(PROFILE_UPLOAD_FOLDER),filename)
 return send_from_directory(str(BASE_DIR/"resources"/"assets"/"images"),"default_profile.png")
@app.route("/favicon.ico")
def favicon(): return send_from_directory(str(BASE_DIR/"resources"/"assets"/"images"),"Nexora.png",mimetype="image/png")
@app.route("/health")
def health(): return {"status":"ok"},200

def repair_missing_student_profiles():
 conn=get_db_connection(); cur=conn.cursor()
 try:
  sql=("INSERT INTO student_profiles (user_id,profile_completed) SELECT u.id,0 FROM users u WHERE u.role='student' AND NOT EXISTS (SELECT 1 FROM student_profiles sp WHERE sp.user_id=u.id) ON CONFLICT (user_id) DO NOTHING" if using_postgres() else "INSERT OR IGNORE INTO student_profiles (user_id,profile_completed) SELECT u.id,0 FROM users u WHERE u.role='student' AND NOT EXISTS (SELECT 1 FROM student_profiles sp WHERE sp.user_id=u.id)")
  cur.execute(sql); conn.commit()
 except Exception as exc: conn.rollback(); print("student profile repair skipped:",exc)
 finally: cur.close(); conn.close()
initialize_database(); ensure_classroom_schema(); ensure_classwork_submission_schema(); ensure_classwork_score_schema(); repair_missing_student_profiles()
for bp in (auth,password,student,student_classwork,student_gradebook,student_classmates,supervisor,admin,classroom,classwork,classwork_submissions,classwork_grading,classwork_scores,classwork_gradebook,classwork_gradebook_export,classwork_ml_insights,performance_reports,admin_reports_overview,notifications_bp): app.register_blueprint(bp)
@app.context_processor
def inject_notifications():
 if "user_id" not in session:return {"notifications":[],"recent_notifications":[],"unread_count":0,"sidebar_profile":None}
 uid=session["user_id"]; sidebar=None
 try:
  conn=get_db_connection()
  try:
   user=conn.execute("SELECT id,username,email,role FROM users WHERE id=?",(uid,)).fetchone()
   if user:
    sidebar={"id":user["id"],"username":user["username"],"email":user["email"],"role":user["role"],"profile_picture":None}
    if user["role"]=="student":
     p=conn.execute("SELECT first_name,last_name,profile_picture FROM student_profiles WHERE user_id=?",(uid,)).fetchone()
     if p: sidebar.update({"first_name":p["first_name"],"last_name":p["last_name"],"profile_picture":p["profile_picture"]})
  finally: conn.close()
  return {"notifications":get_user_notifications(uid,limit=20),"recent_notifications":get_recent_notifications(uid,days=7,limit=10),"unread_count":get_unread_count(uid),"sidebar_profile":sidebar}
 except Exception as exc: print("inject_notifications failed:",exc); return {"notifications":[],"recent_notifications":[],"unread_count":0,"sidebar_profile":sidebar}
if __name__=="__main__": app.run(debug=app.debug)
