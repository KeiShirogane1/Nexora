from datetime import datetime, timedelta
from flask import Blueprint, jsonify, redirect, render_template, session, flash
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection, using_postgres

admin_trash=Blueprint("admin_trash",__name__)


def ensure_trash_schema(conn):
    if using_postgres():
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_user_trash (id SERIAL PRIMARY KEY,user_id INTEGER UNIQUE,username TEXT,email TEXT,role TEXT,deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS admin_user_trash (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE,username TEXT,email TEXT,role TEXT,deleted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()


def purge_expired(conn):
    cutoff=datetime.now()-timedelta(days=30)
    rows=conn.execute("SELECT user_id FROM admin_user_trash WHERE deleted_at < ?",(cutoff,)).fetchall()
    for row in rows:
        uid=row[0]
        # Preserve historical records when foreign keys prevent physical deletion.
        try:
            conn.execute("DELETE FROM users WHERE id=? AND status='inactive'",(uid,))
        except Exception:
            pass
        conn.execute("DELETE FROM admin_user_trash WHERE user_id=?",(uid,))
    conn.commit()


def seed_existing(conn):
    inactive=conn.execute("SELECT id,username,email,role FROM users WHERE status='inactive'").fetchall()
    for u in inactive:
        uid=u[0]
        exists=conn.execute("SELECT 1 FROM admin_user_trash WHERE user_id=?",(uid,)).fetchone()
        if not exists:
            conn.execute("INSERT INTO admin_user_trash (user_id,username,email,role) VALUES (?,?,?,?)",(uid,u[1],u[2],u[3]))
    conn.commit()


@admin_trash.route("/admin/trash")
@role_required("admin")
def trash():
    conn=get_db_connection()
    try:
        ensure_trash_schema(conn); seed_existing(conn); purge_expired(conn)
        rows=conn.execute("SELECT id,user_id,username,email,role,deleted_at FROM admin_user_trash ORDER BY deleted_at DESC").fetchall()
    finally: conn.close()
    return render_template("admin/trash.html",trash_items=rows,active_page="trash")


@admin_trash.route("/admin/trash/data")
@role_required("admin")
def trash_data():
    conn=get_db_connection()
    try:
        ensure_trash_schema(conn); seed_existing(conn); purge_expired(conn)
        rows=conn.execute("SELECT user_id FROM admin_user_trash ORDER BY deleted_at DESC").fetchall()
        return jsonify({"ids":[int(r[0]) for r in rows]})
    finally: conn.close()


@admin_trash.route("/admin/trash/delete/<int:user_id>",methods=["POST"])
@role_required("admin")
def move_to_trash(user_id):
    conn=get_db_connection()
    try:
        ensure_trash_schema(conn)
        user=conn.execute("SELECT id,username,email,role,status FROM users WHERE id=? AND role!='admin'",(user_id,)).fetchone()
        if not user:
            return jsonify({"success":False,"error":"User not found"}),404
        conn.execute("""INSERT INTO admin_user_trash (user_id,username,email,role,deleted_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET deleted_at=CURRENT_TIMESTAMP,username=excluded.username,email=excluded.email,role=excluded.role""",(user[0],user[1],user[2],user[3]))
        conn.execute("UPDATE users SET status='inactive' WHERE id=? AND role!='admin'",(user_id,)); conn.commit()
        return jsonify({"success":True})
    except Exception as exc:
        conn.rollback(); return jsonify({"success":False,"error":str(exc)}),500
    finally: conn.close()


@admin_trash.route("/admin/trash/restore/<int:user_id>",methods=["POST"])
@role_required("admin")
def restore(user_id):
    conn=get_db_connection()
    try:
        ensure_trash_schema(conn)
        row=conn.execute("SELECT role FROM admin_user_trash WHERE user_id=?",(user_id,)).fetchone()
        if not row:return redirect("/admin/trash")
        conn.execute("UPDATE users SET status='active' WHERE id=? AND role!='admin'",(user_id,)); conn.execute("DELETE FROM admin_user_trash WHERE user_id=?",(user_id,)); conn.commit()
    finally: conn.close()
    flash("User restored successfully.","success"); return redirect("/admin/trash")


@admin_trash.route("/admin/trash/permanent/<int:user_id>",methods=["POST"])
@role_required("admin")
def permanent_delete(user_id):
    conn=get_db_connection()
    try:
        ensure_trash_schema(conn)
        user=conn.execute("SELECT role FROM users WHERE id=?",(user_id,)).fetchone()
        if user and user[0] != 'admin':
            # Remove the account only after clearing known ownership/membership rows.
            for table,column in (("classroom_students","student_id"),("student_assignments","student_id"),("notifications","user_id"),("attendance","student_id"),("logs","student_id"),("documents","student_id"),("tasks","student_id"),("internships","student_id"),("feedback","student_id"),("classwork_scores","student_id"),("classwork_submissions","student_id")):
                try: conn.execute(f"DELETE FROM {table} WHERE {column}=?",(user_id,))
                except Exception: pass
            try: conn.execute("DELETE FROM student_profiles WHERE user_id=?",(user_id,))
            except Exception: pass
            try: conn.execute("DELETE FROM users WHERE id=?",(user_id,))
            except Exception:
                # Last-resort anonymization keeps FK-linked historical data safe.
                conn.execute("UPDATE users SET username=?,email=NULL,status='inactive' WHERE id=?",(f"deleted_{user_id}",user_id))
            conn.execute("DELETE FROM admin_user_trash WHERE user_id=?",(user_id,)); conn.commit()
    finally: conn.close()
    flash("User permanently removed from the account directory.","success"); return redirect("/admin/trash")
