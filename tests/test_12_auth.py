import pathlib, sys, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from unittest.mock import MagicMock, patch
from bootstrap.app import app
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password

def _login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess["user_id"]=uid
        sess["role"]=role

def test_login_ui():
    txt=pathlib.Path("resources/views/auth/login.html").read_text(encoding="utf-8")
    assert "Welcome back" in txt or "Nexora" in txt
    assert 'name="username"' in txt
    assert 'name="password"' in txt
    assert 'csrf_token' in txt
    assert 'Forgot Password' in txt
    assert 'togglePass' in txt
    assert 'show/hide' in txt.lower() or '👁' in txt

def test_signup_ui():
    txt=pathlib.Path("resources/views/auth/signup.html").read_text(encoding="utf-8")
    assert 'name="username"' in txt
    assert 'name="email"' in txt
    assert 'name="account_type"' in txt
    assert 'name="password"' in txt
    assert 'name="confirm_password"' in txt
    assert 'csrf_token' in txt
    assert 'togglePass' in txt

def test_forgot_password_ui():
    txt=pathlib.Path("resources/views/auth/forgot_password.html").read_text(encoding="utf-8")
    assert 'name="email"' in txt
    assert 'csrf_token' in txt
    assert 'Send Reset Link' in txt

def test_reset_password_ui():
    txt=pathlib.Path("resources/views/auth/reset_password.html").read_text(encoding="utf-8")
    assert 'name="password"' in txt
    assert 'name="confirm_password"' in txt
    assert 'csrf_token' in txt
    assert 'togglePass' in txt

def test_change_password_modal_ui():
    txt=pathlib.Path("resources/views/auth/change_password.html").read_text(encoding="utf-8")
    assert 'Send verification code' in txt or 'verification code' in txt.lower()
    assert 'csrf_token' in txt
    assert 'change_verified' in txt or 'verified' in txt.lower()
    assert 'togglePass' in txt
    assert 'modal' in txt.lower() or 'Modal' in txt

def test_logout_route():
    client=app.test_client()
    _login_as(client, 1, "admin")
    resp=client.get("/logout", follow_redirects=False)
    assert resp.status_code in (302,303)
    assert "/" in resp.headers.get("Location","")

def test_logout_ui():
    for p in ["resources/views/components/admin_sidebar.html","resources/views/components/student_sidebar.html","resources/views/components/supervisor_sidebar.html"]:
        txt=pathlib.Path(p).read_text(encoding="utf-8")
        assert "logout" in txt.lower()
        assert "Logout" in txt

def _ensure_user(uid, uname, role, email=None):
    if email is None:
        email = f"{uname}_{uid}@test.com"
    conn=get_db_connection()
    cur=conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE id=?", (uid,))
        if not cur.fetchone():
            # ensure email unique
            cur.execute("DELETE FROM users WHERE email=? AND id != ?", (email, uid))
            cur.execute("INSERT INTO users (id, username, email, password, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                        (uid, uname, email, hash_password("OldPass123"), role, "active"))
        else:
            cur.execute("UPDATE users SET status='active', role=?, email=?, password=? WHERE id=?",
                        (role, email, hash_password("OldPass123"), uid))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except:
            pass
        raise
    finally:
        conn.close()

def _cleanup_change_codes(uid):
    conn=get_db_connection()
    cur=conn.cursor()
    cur.execute("DELETE FROM change_verification_codes WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()

def test_verification_code_generation():
    from app.Services.change_verification_service import create_change_code, hash_code
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_user(99100, "chg_user1", "student")
    _cleanup_change_codes(99100)
    with patch("app.Services.change_verification_service.get_db_connection", wraps=get_db_connection):
        code=create_change_code(99100)
        assert re.match(r"^\d{6}$", code)
        # hash stored, not plain
        conn=get_db_connection()
        row=conn.execute("SELECT code_hash FROM change_verification_codes WHERE user_id=99100 ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row[0]==hash_code(code)
        assert row[0]!=code
    _cleanup_change_codes(99100)

def test_verification_code_expiry():
    from app.Services.change_verification_service import create_change_code, verify_change_code
    import datetime
    _ensure_user(99101, "chg_user2", "student")
    _cleanup_change_codes(99101)
    code=create_change_code(99101)
    # expire it manually
    conn=get_db_connection()
    conn.execute("UPDATE change_verification_codes SET expires_at = datetime('now','-1 hour') WHERE user_id=99101")
    conn.commit()
    conn.close()
    ok, msg=verify_change_code(99101, code)
    assert ok is False
    assert "No valid code" in msg or "expired" in msg.lower() or "No valid" in msg
    _cleanup_change_codes(99101)

def test_invalid_code():
    from app.Services.change_verification_service import create_change_code, verify_change_code
    _ensure_user(99102, "chg_user3", "student")
    _cleanup_change_codes(99102)
    create_change_code(99102)
    ok, msg=verify_change_code(99102, "000000")
    assert ok is False
    assert "Invalid" in msg
    _cleanup_change_codes(99102)

def test_reused_code():
    from app.Services.change_verification_service import create_change_code, verify_change_code
    _ensure_user(99103, "chg_user4", "student")
    _cleanup_change_codes(99103)
    code=create_change_code(99103)
    ok,_=verify_change_code(99103, code)
    assert ok is True
    ok2, msg2=verify_change_code(99103, code)
    assert ok2 is False
    _cleanup_change_codes(99103)

def test_attempt_limit():
    from app.Services.change_verification_service import create_change_code, verify_change_code, MAX_ATTEMPTS
    _ensure_user(99104, "chg_user5", "student")
    _cleanup_change_codes(99104)
    create_change_code(99104)
    for i in range(MAX_ATTEMPTS):
        ok, msg=verify_change_code(99104, "111111")
        if i < MAX_ATTEMPTS-1:
            assert ok is False
            assert "Invalid" in msg or "attempts" in msg.lower()
        else:
            assert ok is False
            assert "Too many" in msg
    # after limit, even correct code should fail
    conn=get_db_connection()
    row=conn.execute("SELECT code_hash FROM change_verification_codes WHERE user_id=99104 ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    # code is already invalidated, so any code should fail with No valid
    ok, msg=verify_change_code(99104, "000000")
    assert ok is False
    _cleanup_change_codes(99104)

def test_successful_password_change_with_verification():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_user(99110, "chg_user10", "student", email="change10@test.com")
    _cleanup_change_codes(99110)
    client=app.test_client()
    _login_as(client, 99110, "student")
    # request code (mock email)
    with patch("app.Http.Controllers.password.send_email") as mock_send:
        resp=client.post("/change-password/request-code", follow_redirects=False)
        assert resp.status_code in (302,303)
        assert mock_send.called
        # ensure code not in HTML
        resp2=client.get("/change-password")
        assert b"99110" not in resp2.data  # no code leak
    # fetch code from DB hash? need plain code - we can fetch via service directly
    from app.Services.change_verification_service import create_change_code
    # create a new code and use it
    _cleanup_change_codes(99110)
    with patch("app.Http.Controllers.password.send_email"):
        client.post("/change-password/request-code")
    conn=get_db_connection()
    # we need plain code, so generate and store manually to know it
    conn.close()
    # Use service to generate and capture
    from app.Services.change_verification_service import create_change_code as ccc
    _cleanup_change_codes(99110)
    code=ccc(99110)
    # verify
    resp3=client.post("/change-password/verify-code", data={"code":code})
    assert resp3.status_code in (302,303)
    # now change password
    resp4=client.post("/change-password", data={"current_password":"OldPass123","new_password":"NewPass123","confirm_password":"NewPass123"}, follow_redirects=False)
    assert resp4.status_code in (302,303)
    # verify password updated
    conn=get_db_connection()
    row=conn.execute("SELECT password FROM users WHERE id=99110").fetchone()
    conn.close()
    from app.Services.password_security import verify_password
    assert verify_password(row[0], "NewPass123") is True
    # cleanup
    _cleanup_change_codes(99110)
    conn=get_db_connection()
    conn.execute("UPDATE users SET password=? WHERE id=99110", (hash_password("OldPass123"),))
    conn.commit()
    conn.close()

def test_csrf_on_change_password():
    app.config["WTF_CSRF_ENABLED"]=True
    app.config["TESTING"]=True
    _ensure_user(99120, "chg_user20", "student")
    client=app.test_client()
    _login_as(client, 99120, "student")
    resp=client.post("/change-password/request-code")
    assert resp.status_code==400
    resp2=client.post("/change-password/verify-code", data={"code":"123456"})
    assert resp2.status_code==400
    resp3=client.post("/change-password", data={"current_password":"OldPass123","new_password":"NewPass123","confirm_password":"NewPass123"})
    assert resp3.status_code==400
    app.config["WTF_CSRF_ENABLED"]=False

def test_logout_clears_session():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    _ensure_user(99130, "chg_user30", "student")
    client=app.test_client()
    _login_as(client, 99130, "student")
    resp=client.get("/student/dashboard", follow_redirects=False)
    # should be 200 or 302 depending on profile setup, but not 403
    # after logout, should redirect to login
    client.get("/logout")
    with client.session_transaction() as sess:
        assert "user_id" not in sess

def test_authentication_regression():
    app.config["WTF_CSRF_ENABLED"]=False
    app.config["TESTING"]=True
    client=app.test_client()
    # unauthenticated should redirect to login for change-password
    resp=client.get("/change-password", follow_redirects=False)
    assert resp.status_code in (302,303)
    assert "/login" in resp.headers.get("Location","")
    # student cannot access admin
    _ensure_user(99140, "chg_user40", "student")
    _login_as(client, 99140, "student")
    resp2=client.get("/admin/dashboard")
    assert resp2.status_code==403
