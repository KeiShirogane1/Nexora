from flask import Blueprint,render_template,request,redirect,url_for,session,flash,current_app
from app.Models.db import get_db_connection,using_postgres
from app.Services.password_security import hash_password,verify_password
from app.Services.notification_service import create_notification
import re

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
 form_data={"username":"","email":"","account_type":""}

 if request.method=="POST":
  username=request.form.get("username","").strip()
  email=request.form.get("email","").strip().lower()
  password=request.form.get("password","")
  confirm_password=request.form.get("confirm_password","")
  account_type=request.form.get("account_type","").strip().lower()

  form_data={
   "username":username,
   "email":email,
   "account_type":account_type,
  }

  if not username:
   flash("Username is required.","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if len(username)<3:
   flash("Username must be at least 3 characters.","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if not re.match(r"^[A-Za-z0-9_.-]+$",username):
   flash("Username may only contain letters, numbers, underscores, periods, and hyphens.","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if not email:
   flash("Email address is required.","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$",email):
   flash("Enter a valid email address.","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if account_type not in ("student","supervisor"):
   flash("Please select an account type.","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if not password:
   flash("Password is required.","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if not confirm_password:
   flash("Please confirm your password.","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if password!=confirm_password:
   flash("Passwords do not match ❌","danger")
   return render_template("auth/signup.html",form_data=form_data)
  if len(password)<8:
   flash("Password must be at least 8 characters ❌","danger")
   return render_template("auth/signup.html",form_data=form_data)

  conn=get_db_connection();cur=conn.cursor()
  try:
   cur.execute("SELECT id FROM users WHERE username=?",(username,))
   username_exists=cur.fetchone() is not None
   cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?)",(email,))
   email_exists=cur.fetchone() is not None

   if username_exists or email_exists:
    if username_exists:
     flash("Username already exists.","danger")
    if email_exists:
     flash("Email address already exists.","danger")
    return render_template("auth/signup.html",form_data=form_data)

   pending_role="pending_student" if account_type=="student" else "pending_supervisor"
   insert_sql="INSERT INTO users (username,email,password,role) VALUES (?,?,?,?)"
   insert_sql+=" RETURNING id" if using_postgres() else ""
   cur.execute(insert_sql,(username,email,hash_password(password),pending_role))
   user_row=cur.fetchone() if using_postgres() else None
   user_id=(user_row["id"] if user_row and "id" in user_row.keys() else user_row[0] if user_row else None) if using_postgres() else cur.lastrowid

   if not user_id:
    raise RuntimeError("Could not determine the new user ID.")

   if account_type=="student":
    cur.execute("INSERT INTO student_profiles (user_id,profile_completed) VALUES (?,0)",(user_id,))

   conn.commit()
  except Exception:
   conn.rollback()
   raise
  finally:
   cur.close()
   conn.close()

  account_label="student" if account_type=="student" else "supervisor"
  try:
   admin_conn=get_db_connection();admin_cur=admin_conn.cursor()
   try:
    admin_cur.execute("SELECT id FROM users WHERE role='admin' AND COALESCE(status,'active')<>'inactive'")
    admin_ids=[row[0] for row in admin_cur.fetchall()]
   finally:
    admin_cur.close()
    admin_conn.close()

   for admin_id in admin_ids:
    try:
     create_notification(
      admin_id,
      "New account awaiting approval",
      f"{username} ({email}) requested a {account_label} account.",
      "system",
      "/admin/users",
     )
    except Exception as exc:
     current_app.logger.warning("Could not create signup notification for admin %s: %s",admin_id,exc)
  except Exception as exc:
   current_app.logger.warning("Could not load admins for signup notification: %s",exc)

  flash("Account created successfully. Wait for approval.","success")
  return redirect(url_for("auth.login"))

 return render_template("auth/signup.html",form_data=form_data)
