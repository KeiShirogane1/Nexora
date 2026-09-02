from flask import Blueprint,render_template,request,redirect,url_for,session,flash
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password,verify_password

auth=Blueprint("auth",__name__)

@auth.route("/logout")
def logout(): session.clear(); return redirect("/")

def get_user(identifier,password):
 conn=get_db_connection(); cur=conn.cursor()
 try:
  cur.execute("SELECT id,username,email,password,role,status FROM users WHERE username=? OR LOWER(email)=LOWER(?) LIMIT 1",(identifier,identifier)); user=cur.fetchone()
  if not user:return None
  if not verify_password(user["password"],password):return None
  if user["status"]=="inactive":return "inactive"
  return user
 finally:cur.close();conn.close()

@auth.route("/")
def welcome():return render_template("welcome.html")

@auth.route("/login",methods=["GET","POST"])
def login():
 if request.method=="POST":
  username=request.form.get("username","").strip(); password=request.form.get("password",""); user=get_user(username,password)
  if user=="inactive":session["login_error"]="Your account has been deactivated. Please contact the administrator.";session["login_username"]=username;return redirect(url_for("auth.login"))
  if user and user["role"] in ("pending_student","pending_supervisor"):session["login_error"]="Your account is awaiting administrator approval. You will be notified once approved.";session["login_username"]=username;return redirect(url_for("auth.login"))
  if user and user["role"]=="rejected":session["login_error"]="Your account request was not approved. Please contact the administrator.";session["login_username"]=username;return redirect(url_for("auth.login"))
  if user:
   role=user["role"]; session.clear(); session["user_id"]=user["id"];session["role"]=role
   if role=="supervisor":
    conn=get_db_connection();cur=conn.cursor()
    try:
     cur.execute("UPDATE users SET session_version=COALESCE(session_version,0)+1 WHERE id=?",(user["id"],));cur.execute("SELECT session_version FROM users WHERE id=?",(user["id"],));row=cur.fetchone();conn.commit();session["session_version"]=int(row[0]) if row else 0
    finally:cur.close();conn.close()
    return redirect(url_for("supervisor.supervisor_dashboard"))
   if role=="student":return redirect(url_for("student.student_dashboard"))
   if role=="admin":return redirect(url_for("admin.admin_dashboard"))
  session["login_error"]="Invalid username or password ❌";session["login_username"]=username;return redirect(url_for("auth.login"))
 error=session.pop("login_error",None); entered_username=session.pop("login_username",""); return render_template("auth/login.html",error=error,entered_username=entered_username)

@auth.route("/signup",methods=["GET","POST"])
def signup():
 if request.method=="POST":
  username=request.form.get("username","").strip();email=request.form.get("email","").strip().lower();password=request.form.get("password","");confirm_password=request.form.get("confirm_password","");account_type=request.form.get("account_type","").strip().lower()
  if not username:flash("Username is required.","danger");return render_template("auth/signup.html")
  if not email:flash("Email address is required.","danger");return render_template("auth/signup.html")
  if account_type not in ("student","supervisor"):flash("Please select an account type.","danger");return render_template("auth/signup.html")
  if not password:flash("Password is required.","danger");return render_template("auth/signup.html")
  if not confirm_password:flash("Please confirm your password.","danger");return render_template("auth/signup.html")
  if password!=confirm_password:flash("Passwords do not match ❌","danger");return render_template("auth/signup.html")
  if len(password)<8:flash("Password must be at least 8 characters ❌","danger");return render_template("auth/signup.html")
  conn=get_db_connection();cur=conn.cursor()
  try:
   if cur.execute("SELECT id FROM users WHERE username=? OR LOWER(email)=LOWER(?)",(username,email)).fetchone():flash("Username or email already exists ❌","danger");return render_template("auth/signup.html")
   pending_role="pending_student" if account_type=="student" else "pending_supervisor";cur.execute("INSERT INTO users (username,email,password,role) VALUES (?,?,?,?)",(username,email,hash_password(password),pending_role));user_id=cur.lastrowid
   if account_type=="student":cur.execute("INSERT INTO student_profiles (user_id,profile_completed) VALUES (?,0)",(user_id,))
   conn.commit()
  except Exception:conn.rollback();raise
  finally:cur.close();conn.close()
  flash("Account created successfully. Wait for approval.","success");return redirect(url_for("auth.login"))
 return render_template("auth/signup.html")
