import os
from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.utils import secure_filename
from app.Http.Middleware.security import role_required
from app.Models.db import get_db_connection

supervisor_profile_photo=Blueprint("supervisor_profile_photo",__name__)

@supervisor_profile_photo.route("/supervisor/profile/photo",methods=["POST"])
@role_required("supervisor")
def update_photo():
    file=request.files.get("profile_picture")
    if not file or not file.filename:return jsonify({"ok":False,"error":"No image received"}),400
    name=secure_filename(file.filename); ext=name.rsplit('.',1)[-1].lower() if '.' in name else ''
    if ext not in {"png","jpg","jpeg","gif"}:return jsonify({"ok":False,"error":"Image type not allowed"}),400
    file.seek(0,os.SEEK_END); size=file.tell(); file.seek(0)
    if size>2*1024*1024:return jsonify({"ok":False,"error":"Image too large (max 2MB)"}),400
    filename=f"supervisor_{session['user_id']}_profile.jpg"; path=os.path.join(current_app.config["PROFILE_UPLOAD_FOLDER"],filename); file.save(path)
    conn=get_db_connection()
    try:
        conn.execute("UPDATE users SET profile_picture=? WHERE id=? AND role='supervisor'",(filename,session["user_id"])); conn.commit()
    finally: conn.close()
    return jsonify({"ok":True,"url":f"/uploads/profile_pictures/{filename}"})
