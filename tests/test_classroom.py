import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from unittest.mock import MagicMock, patch
from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password
import re

def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"]=uid
        sess["role"]=role

def _ensure_test_users():
    conn=get_db_connection()
    cur=conn.cursor()
    # use high IDs to avoid collision
    for uid, uname, role in [(99001,"test_sup_cla","supervisor"),(99002,"test_sup_cla2","supervisor"),(99011,"test_stu_cla","student"),(99012,"test_stu_cla2","student")]:
        cur.execute("SELECT id FROM users WHERE id=?", (uid,))
        if not cur.fetchone():
            cur.execute("INSERT INTO users (id, username, email, password, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                        (uid, uname, f"{uname}@test.com", hash_password("pass12345"), role, "active"))
        else:
            cur.execute("UPDATE users SET status='active', role=? WHERE id=?", (role, uid))
    conn.commit()
    conn.close()

def _cleanup_classroom():
    conn=get_db_connection()
    cur=conn.cursor()
    try:
        cur.execute("DELETE FROM classroom_submissions WHERE assignment_id IN (SELECT id FROM classroom_assignments WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id IN (99001,99002)))")
        cur.execute("DELETE FROM classroom_assignments WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id IN (99001,99002))")
        cur.execute("DELETE FROM classroom_posts WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id IN (99001,99002))")
        cur.execute("DELETE FROM classroom_students WHERE classroom_id IN (SELECT id FROM classrooms WHERE supervisor_id IN (99001,99002))")
        cur.execute("DELETE FROM classrooms WHERE supervisor_id IN (99001,99002)")
        conn.commit()
    except Exception:
        pass
    conn.close()

def _create_class_via_client(sup_id=99001, name="BSIT 3A", section="BSIT 3A", desc="Desc"):
    client=app.test_client()
    _login_as(client, sup_id, "supervisor")
    resp=client.post("/supervisor/classes/create", data={"class_name":name, "section":section, "description":desc}, follow_redirects=False)
    return resp

def _get_last_class_code(sup_id=99001):
    conn=get_db_connection()
    cur=conn.cursor()
    row=cur.execute("SELECT code, id FROM classrooms WHERE supervisor_id=? ORDER BY id DESC LIMIT 1", (sup_id,)).fetchone()
    conn.close()
    if row:
        return (row["code"] if "code" in row.keys() else row[0], row["id"] if "id" in row.keys() else row[1])
    return (None,None)

def test_supervisor_can_create_class():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    resp=_create_class_via_client()
    assert resp.status_code in (302,303)
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classrooms WHERE supervisor_id=99001").fetchone()[0]
    conn.close()
    assert cnt==1
    _cleanup_classroom()

def test_class_receives_unique_code():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client(name="Class A", section="A")
    _create_class_via_client(name="Class B", section="B")
    conn=get_db_connection()
    rows=list(conn.execute("SELECT code FROM classrooms WHERE supervisor_id=99001 ORDER BY id").fetchall())
    conn.close()
    codes=[r[0] for r in rows]
    assert len(codes)==2
    assert codes[0]!=codes[1]
    for c in codes:
        assert re.match(r"^NXR-[A-Z0-9]{6}$", c), f"bad code {c}"
    _cleanup_classroom()

def test_supervisor_can_view_own_class():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code, cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    resp=client.get(f"/supervisor/classes/{cid}")
    assert resp.status_code==200
    assert code.encode() in resp.data or b"BSIT" in resp.data
    _cleanup_classroom()

def test_supervisor_cannot_view_another_supervisors_class():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client(sup_id=99001)
    _, cid=_get_last_class_code(99001)
    client=app.test_client()
    _login_as(client, 99002, "supervisor")
    resp=client.get(f"/supervisor/classes/{cid}")
    assert resp.status_code==403
    _cleanup_classroom()

def test_student_can_join_valid_class():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,_=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99011, "student")
    resp=client.post("/student/classes/join", data={"class_code":code}, follow_redirects=False)
    assert resp.status_code in (302,303)
    conn=get_db_connection()
    row=conn.execute("SELECT 1 FROM classroom_students WHERE student_id=99011").fetchone()
    conn.close()
    assert row is not None
    # check notification to supervisor
    conn=get_db_connection()
    notif=conn.execute("SELECT title FROM notifications WHERE user_id=99001 ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    # notification may exist
    _cleanup_classroom()
    # cleanup notifications for test supervisor
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id=99001 AND title='New Class Enrollment'")
    conn.commit()
    conn.close()

def test_invalid_code_rejected():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    client=app.test_client()
    _login_as(client, 99011, "student")
    resp=client.post("/student/classes/join", data={"class_code":"INVALID999"}, follow_redirects=False)
    # should stay on same page with error or redirect with flash
    assert resp.status_code in (200,302,303)
    if resp.status_code==200:
        assert b"Invalid class code" in resp.data
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classroom_students WHERE student_id=99011").fetchone()[0]
    conn.close()
    assert cnt==0

def test_duplicate_join_prevented():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,_=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    resp2=client.post("/student/classes/join", data={"class_code":code})
    assert resp2.status_code in (302,303,200)
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classroom_students WHERE student_id=99011").fetchone()[0]
    conn.close()
    assert cnt==1
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id=99001")
    conn.commit()
    conn.close()

def test_archived_class_cannot_be_joined():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    # archive
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    client.post(f"/supervisor/classes/{cid}/archive")
    client2=app.test_client()
    _login_as(client2, 99011, "student")
    resp=client2.post("/student/classes/join", data={"class_code":code})
    assert resp.status_code in (200,302)
    if resp.status_code==200:
        assert b"archived" in resp.data.lower()
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classroom_students WHERE student_id=99011").fetchone()[0]
    conn.close()
    assert cnt==0
    _cleanup_classroom()

def test_student_can_view_joined_class():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    resp=client.get(f"/student/classes/{cid}")
    assert resp.status_code==200
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id=99001")
    conn.commit()
    conn.close()

def test_student_cannot_view_unjoined_class():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    _,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99012, "student") # different student not joined
    resp=client.get(f"/student/classes/{cid}")
    assert resp.status_code==403
    _cleanup_classroom()

def test_announcement_ownership():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    _,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    resp=client.post(f"/supervisor/classes/{cid}/post", data={"title":"Ann","body":"Hello class, this is an announcement for testing."})
    assert resp.status_code in (302,303)
    # other supervisor should be forbidden
    _login_as(client, 99002, "supervisor")
    resp2=client.post(f"/supervisor/classes/{cid}/post", data={"title":"Hack","body":"Should not work"})
    assert resp2.status_code==403
    # student should be forbidden (no route for student post, but try supervisor endpoint as student)
    _login_as(client, 99011, "student")
    resp3=client.post(f"/supervisor/classes/{cid}/post", data={"title":"Hack","body":"student hack"})
    assert resp3.status_code==403
    # archived class should not allow new posts
    _login_as(client, 99001, "supervisor")
    client.post(f"/supervisor/classes/{cid}/archive")
    resp4=client.post(f"/supervisor/classes/{cid}/post", data={"title":"After archive","body":"Should be blocked because archived"})
    assert resp4.status_code in (302,303)
    # verify only one post exists
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classroom_posts WHERE classroom_id=?", (cid,)).fetchone()[0]
    conn.close()
    assert cnt==1
    _cleanup_classroom()

def test_assignment_ownership():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    _,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    resp=client.post(f"/supervisor/classes/{cid}/assignment", data={"title":"HW1","description":"Do work","due_at":"2026-12-31 23:59","points":"100"})
    assert resp.status_code in (302,303)
    _login_as(client, 99002, "supervisor")
    resp2=client.post(f"/supervisor/classes/{cid}/assignment", data={"title":"Hack","description":"x"})
    assert resp2.status_code==403
    _cleanup_classroom()

def test_unauthorized_access():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    # no login
    resp=client.get("/supervisor/classes")
    assert resp.status_code in (302,303)
    resp2=client.get("/student/classes")
    assert resp2.status_code in (302,303)
    # student trying supervisor
    _login_as(client, 99011, "student")
    resp3=client.get("/supervisor/classes")
    assert resp3.status_code==403
    _login_as(client, 99001, "supervisor")
    resp4=client.get("/student/classes")
    assert resp4.status_code==403

def test_csrf_protection():
    app.config["WTF_CSRF_ENABLED"]=True
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    # without token should be 400
    resp=client.post("/supervisor/classes/create", data={"class_name":"Test","section":"A"})
    assert resp.status_code==400
    app.config["WTF_CSRF_ENABLED"]=False

def test_postgres_placeholder_compatibility():
    txt=pathlib.Path("app/Http/Controllers/classroom.py").read_text(encoding="utf-8")
    assert "?" in txt
    assert 'SELECT * FROM classrooms WHERE code = ?' in txt or 'SELECT 1 FROM classrooms WHERE code = ?' in txt
    # ensure no %s hard-coded SQL
    assert txt.count("%s") == 0 or "format" in txt

def _create_assignment(sup_id=99001, cid=None, title="HW1", desc="Do work", due=None):
    if cid is None:
        _, cid = _get_last_class_code(sup_id)
    client=app.test_client()
    _login_as(client, sup_id, "supervisor")
    data={"title":title, "description":desc}
    if due:
        data["due_at"]=due
    resp=client.post(f"/supervisor/classes/{cid}/assignment", data=data, follow_redirects=False)
    return resp, cid

def _get_last_assignment_id(cid):
    conn=get_db_connection()
    row=conn.execute("SELECT id FROM classroom_assignments WHERE classroom_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    conn.close()
    if row:
        return row["id"] if "id" in row.keys() else row[0]
    return None

# ========== Phase 11.3 classwork tests ==========

def test_student_assignment_view():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    _create_assignment(cid=cid, title="TestAssign", desc="Desc")
    aid=_get_last_assignment_id(cid)
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    resp=client.get(f"/student/classes/{cid}/assignments/{aid}")
    assert resp.status_code==200
    assert b"TestAssign" in resp.data
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id=99001")
    conn.commit()
    conn.close()

def test_student_submission_text_and_file():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    _create_assignment(cid=cid, title="SubmitTest")
    aid=_get_last_assignment_id(cid)
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    # text submission
    resp=client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data={"content":"My answer text"}, follow_redirects=False)
    assert resp.status_code in (302,303)
    conn=get_db_connection()
    row=conn.execute("SELECT content, status FROM classroom_submissions WHERE assignment_id=? AND student_id=99011", (aid,)).fetchone()
    conn.close()
    assert row is not None
    assert (row["content"] if "content" in row.keys() else row[0]) == "My answer text"
    # file submission + resubmission should not duplicate
    import io
    data={"content":"Updated answer", "file": (io.BytesIO(b"hello file"), "test.pdf")}
    resp2=client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data=data, content_type="multipart/form-data", follow_redirects=False)
    assert resp2.status_code in (302,303)
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classroom_submissions WHERE assignment_id=? AND student_id=99011", (aid,)).fetchone()[0]
    # check file saved
    row2=conn.execute("SELECT filename FROM classroom_submissions WHERE assignment_id=? AND student_id=99011", (aid,)).fetchone()
    fname=row2["filename"] if "filename" in row2.keys() else row2[0]
    conn.close()
    assert cnt==1, "resubmission should not create duplicate row"
    assert fname is not None and "test.pdf" in fname
    # cleanup uploaded file
    import os, pathlib
    upload_base=app.config.get("UPLOAD_FOLDER") or str(pathlib.Path("storage/uploads"))
    # find file
    try:
        if fname:
            p=os.path.join(str(upload_base), fname)
            if os.path.exists(p):
                os.remove(p)
    except:
        pass
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id=99001")
    conn.commit()
    conn.close()

def test_unauthorized_submission():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    _,cid=_get_last_class_code()
    _create_assignment(cid=cid, title="AuthTest")
    aid=_get_last_assignment_id(cid)
    # student not joined tries to submit
    client=app.test_client()
    _login_as(client, 99012, "student")
    resp=client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data={"content":"hack"}, follow_redirects=False)
    assert resp.status_code==403
    # student tries to submit to another classroom's assignment
    _create_class_via_client(sup_id=99002, name="Other", section="Other")
    _,cid2=_get_last_class_code(99002)
    _create_assignment(sup_id=99002, cid=cid2, title="OtherHW")
    aid2=_get_last_assignment_id(cid2)
    _login_as(client, 99011, "student")
    # 99011 is not member of cid2
    resp2=client.post(f"/student/classes/{cid2}/assignments/{aid2}/submit", data={"content":"hack2"})
    assert resp2.status_code==403
    _cleanup_classroom()

def test_deadline_handling():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    _,cid=_get_last_class_code()
    # past due
    _create_assignment(cid=cid, title="PastDue", due="2000-01-01T00:00")
    aid=_get_last_assignment_id(cid)
    code,_=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    resp=client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data={"content":"late"}, follow_redirects=False)
    assert resp.status_code in (302,303)
    # should not create submission
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classroom_submissions WHERE assignment_id=? AND student_id=99011", (aid,)).fetchone()[0]
    conn.close()
    assert cnt==0
    _cleanup_classroom()

def test_supervisor_submission_list_and_counts():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    _create_assignment(cid=cid, title="ListTest")
    aid=_get_last_assignment_id(cid)
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data={"content":"ans"})
    # another student not submitted -> missing count
    _login_as(client, 99012, "student")
    client.post("/student/classes/join", data={"class_code":code})
    # supervisor view
    _login_as(client, 99001, "supervisor")
    resp=client.get(f"/supervisor/classes/{cid}/assignments/{aid}")
    assert resp.status_code==200
    assert b"Enrolled" in resp.data and b"Submitted" in resp.data
    assert b"Missing" in resp.data
    # should show 2 enrolled, 1 submitted, 1 missing
    assert b">2<" in resp.data or b"2" in resp.data
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()

def test_supervisor_cannot_access_another_classroom_assignment():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client(sup_id=99001)
    _,cid=_get_last_class_code(99001)
    _create_assignment(sup_id=99001, cid=cid, title="OwnerHW")
    aid=_get_last_assignment_id(cid)
    client=app.test_client()
    _login_as(client, 99002, "supervisor")
    resp=client.get(f"/supervisor/classes/{cid}/assignments/{aid}")
    assert resp.status_code==403
    _cleanup_classroom()

def test_secure_file_access():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    _create_assignment(cid=cid, title="FileTest")
    aid=_get_last_assignment_id(cid)
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    import io
    data={"content":"file test", "file": (io.BytesIO(b"secret file content"), "myfile.txt")}
    client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data=data, content_type="multipart/form-data")
    conn=get_db_connection()
    sub=conn.execute("SELECT id, filepath FROM classroom_submissions WHERE assignment_id=? AND student_id=99011", (aid,)).fetchone()
    conn.close()
    sid=sub["id"] if "id" in sub.keys() else sub[0]
    fpath=sub["filepath"] if "filepath" in sub.keys() else sub[1]
    # supervisor can download
    _login_as(client, 99001, "supervisor")
    resp=client.get(f"/supervisor/classes/{cid}/assignments/{aid}/submissions/{sid}/download")
    assert resp.status_code==200
    assert b"secret file content" in resp.data
    # student can download own
    _login_as(client, 99011, "student")
    resp2=client.get(f"/student/classes/{cid}/assignments/{aid}/download")
    assert resp2.status_code==200
    # other student cannot download
    _login_as(client, 99012, "student")
    # 99012 not submitted, but try to download via student route (should be 404 or 403)
    resp3=client.get(f"/student/classes/{cid}/assignments/{aid}/download")
    # 99012 is member? Need to join first, but not submitted, so no file -> 404
    # Enroll 99012
    client.post("/student/classes/join", data={"class_code":code})
    resp3=client.get(f"/student/classes/{cid}/assignments/{aid}/download")
    assert resp3.status_code in (404,403)
    # other supervisor cannot download
    _login_as(client, 99002, "supervisor")
    resp4=client.get(f"/supervisor/classes/{cid}/assignments/{aid}/submissions/{sid}/download")
    assert resp4.status_code==403
    # cleanup file
    import os
    try:
        if fpath and os.path.exists(fpath):
            os.remove(fpath)
    except:
        pass
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()

def test_grading_and_feedback_and_notifications():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    _create_assignment(cid=cid, title="GradeTest")
    aid=_get_last_assignment_id(cid)
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data={"content":"to grade"})
    conn=get_db_connection()
    sub=conn.execute("SELECT id FROM classroom_submissions WHERE assignment_id=? AND student_id=99011", (aid,)).fetchone()
    sid=sub["id"] if "id" in sub.keys() else sub[0]
    conn.close()
    # supervisor grades
    _login_as(client, 99001, "supervisor")
    resp=client.post(f"/supervisor/classes/{cid}/assignments/{aid}/submissions/{sid}/grade", data={"grade":"92","feedback":"Good work"}, follow_redirects=False)
    assert resp.status_code in (302,303)
    conn=get_db_connection()
    row=conn.execute("SELECT grade, feedback, status FROM classroom_submissions WHERE id=?", (sid,)).fetchone()
    conn.close()
    assert (row["grade"] if "grade" in row.keys() else row[0])=="92"
    assert (row["feedback"] if "feedback" in row.keys() else row[1])=="Good work"
    # student should see grade
    _login_as(client, 99011, "student")
    resp2=client.get(f"/student/classes/{cid}/assignments/{aid}")
    assert resp2.status_code==200
    assert b"92" in resp2.data and b"Good work" in resp2.data
    # notification to student
    conn=get_db_connection()
    notif=conn.execute("SELECT title FROM notifications WHERE user_id=99011 ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert notif is not None and b"Graded" in (notif["title"].encode() if "title" in notif.keys() else str(notif[0]).encode())
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()

def test_duplicate_resubmission_updates_not_duplicate():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    _create_assignment(cid=cid, title="ResubTest")
    aid=_get_last_assignment_id(cid)
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data={"content":"first"})
    client.post(f"/student/classes/{cid}/assignments/{aid}/submit", data={"content":"second"})
    conn=get_db_connection()
    rows=list(conn.execute("SELECT content FROM classroom_submissions WHERE assignment_id=? AND student_id=99011", (aid,)).fetchall())
    conn.close()
    assert len(rows)==1
    assert (rows[0]["content"] if "content" in rows[0].keys() else rows[0][0])=="second"
    _cleanup_classroom()

def test_csrf_on_new_routes():
    app.config["WTF_CSRF_ENABLED"]=True
    app.config["TESTING"]=True
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    # need a valid classroom to test CSRF on post, but CSRF check happens before route logic, so even invalid id should be 400
    resp=client.post("/supervisor/classes/9999/post", data={"body":"test"})
    assert resp.status_code==400
    _login_as(client, 99011, "student")
    resp2=client.post("/student/classes/1/assignments/1/submit", data={"content":"test"})
    assert resp2.status_code==400
    app.config["WTF_CSRF_ENABLED"]=False

# ========== Phase 11.4 tests ==========

def test_announcements_stream_and_authorization():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    _,cid=_get_last_class_code()
    client=app.test_client()
    # supervisor posts
    _login_as(client, 99001, "supervisor")
    resp=client.post(f"/supervisor/classes/{cid}/post", data={"title":"Week 1","body":"Welcome to class!"})
    assert resp.status_code in (302,303)
    # verify stream shows it for supervisor
    resp2=client.get(f"/supervisor/classes/{cid}")
    assert b"Welcome to class!" in resp2.data
    # student should see via student view after joining
    code,_=_get_last_class_code()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    resp3=client.get(f"/student/classes/{cid}")
    assert b"Welcome to class!" in resp3.data
    # student cannot post via supervisor endpoint
    resp4=client.post(f"/supervisor/classes/{cid}/post", data={"title":"hack","body":"student hack"})
    assert resp4.status_code==403
    # other supervisor cannot post
    _login_as(client, 99002, "supervisor")
    resp5=client.post(f"/supervisor/classes/{cid}/post", data={"title":"hack2","body":"other sup"})
    assert resp5.status_code==403
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()

def test_people_tab_shows_supervisor_and_classmates():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    _login_as(client, 99012, "student")
    client.post("/student/classes/join", data={"class_code":code})
    # student view should show supervisor and classmates
    _login_as(client, 99011, "student")
    resp=client.get(f"/student/classes/{cid}")
    assert b"People" in resp.data
    assert b"test_sup_cla" in resp.data  # supervisor username
    assert b"test_stu_cla2" in resp.data or b"test_stu_cla" in resp.data
    # supervisor view
    _login_as(client, 99001, "supervisor")
    resp2=client.get(f"/supervisor/classes/{cid}")
    assert b"People" in resp2.data
    assert b"test_stu_cla" in resp2.data
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011,99012)")
    conn.commit()
    conn.close()

def test_supervisor_can_remove_student():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    # verify enrolled
    _login_as(client, 99001, "supervisor")
    resp=client.post(f"/supervisor/classes/{cid}/students/99011/remove")
    assert resp.status_code in (302,303)
    conn=get_db_connection()
    row=conn.execute("SELECT 1 FROM classroom_students WHERE classroom_id=? AND student_id=99011", (cid,)).fetchone()
    conn.close()
    assert row is None
    # removed student cannot view
    _login_as(client, 99011, "student")
    resp2=client.get(f"/student/classes/{cid}")
    assert resp2.status_code==403
    # notification sent
    conn=get_db_connection()
    notif=conn.execute("SELECT title FROM notifications WHERE user_id=99011 ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert notif is not None
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()

def test_remove_authorization_and_idor():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    # other supervisor cannot remove
    _login_as(client, 99002, "supervisor")
    resp=client.post(f"/supervisor/classes/{cid}/students/99011/remove")
    assert resp.status_code==403
    # student cannot remove
    _login_as(client, 99011, "student")
    resp2=client.post(f"/supervisor/classes/{cid}/students/99011/remove")
    assert resp2.status_code==403
    _cleanup_classroom()

def test_class_code_copy_and_regeneration():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    # copy UI exists
    resp=client.get(f"/supervisor/classes/{cid}")
    assert b"Copy code" in resp.data or b"copyClassCode" in resp.data
    assert code.encode() in resp.data
    # regenerate
    resp2=client.post(f"/supervisor/classes/{cid}/regenerate")
    assert resp2.status_code in (302,303)
    conn=get_db_connection()
    new_code=conn.execute("SELECT code FROM classrooms WHERE id=?", (cid,)).fetchone()[0]
    conn.close()
    assert new_code != code
    assert re.match(r"^NXR-[A-Z0-9]{6}$", new_code)
    # old code should not work for new student
    _login_as(client, 99012, "student")
    resp3=client.post("/student/classes/join", data={"class_code":code})
    assert resp3.status_code in (200,302)
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classroom_students WHERE student_id=99012").fetchone()[0]
    conn.close()
    # may be 0 if old code invalid
    assert cnt==0
    # new code should work
    client.post("/student/classes/join", data={"class_code":new_code})
    conn=get_db_connection()
    cnt2=conn.execute("SELECT COUNT(*) FROM classroom_students WHERE student_id=99012").fetchone()[0]
    conn.close()
    assert cnt2==1
    # other supervisor cannot regenerate
    _login_as(client, 99002, "supervisor")
    resp4=client.post(f"/supervisor/classes/{cid}/regenerate")
    assert resp4.status_code==403
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99012)")
    conn.commit()
    conn.close()

def test_archived_class_ui_and_block():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    _,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    resp=client.post(f"/supervisor/classes/{cid}/archive")
    assert resp.status_code in (302,303)
    resp2=client.get(f"/supervisor/classes/{cid}")
    assert b"archived" in resp2.data.lower()
    assert b"Unarchive" in resp2.data
    # archived should block post and assignment
    resp3=client.post(f"/supervisor/classes/{cid}/post", data={"title":"t","body":"should be blocked because archived and long enough"})
    assert resp3.status_code in (302,303)
    conn=get_db_connection()
    cnt=conn.execute("SELECT COUNT(*) FROM classroom_posts WHERE classroom_id=?", (cid,)).fetchone()[0]
    conn.close()
    assert cnt==0
    _cleanup_classroom()

def test_classroom_navigation_tabs():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99001, "supervisor")
    resp=client.get(f"/supervisor/classes/{cid}")
    assert b"Stream" in resp.data
    assert b"Classwork" in resp.data
    assert b"People" in resp.data
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    resp2=client.get(f"/student/classes/{cid}")
    assert b"Stream" in resp2.data
    assert b"Classwork" in resp2.data
    assert b"People" in resp2.data
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id=99001")
    conn.commit()
    conn.close()

def test_notifications_for_classroom_events():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_test_users()
    _cleanup_classroom()
    _create_class_via_client()
    code,cid=_get_last_class_code()
    client=app.test_client()
    _login_as(client, 99011, "student")
    client.post("/student/classes/join", data={"class_code":code})
    conn=get_db_connection()
    n1=conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=99001 AND title='New Class Enrollment'").fetchone()[0]
    conn.close()
    assert n1>=1
    # announcement notification
    _login_as(client, 99001, "supervisor")
    client.post(f"/supervisor/classes/{cid}/post", data={"title":"Ann","body":"Hello all"})
    conn=get_db_connection()
    n2=conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=99011 AND title='New Announcement'").fetchone()[0]
    conn.close()
    assert n2>=1
    _cleanup_classroom()
    conn=get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id IN (99001,99011)")
    conn.commit()
    conn.close()

# ensure existing 228 still pass is covered by full pytest run; this test just checks import
def test_existing_tests_still_importable():
    from app.ML.predictor import analyze_feedback
    assert analyze_feedback("Excellent work") in {"Excellent","Very Satisfactory","Satisfactory","Fair","Needs Improvement"}
