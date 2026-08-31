import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bootstrap.app import app

def test_csrf_token_in_forms():
    # Verify that POST forms contain csrf_token
    views = list(pathlib.Path("resources/views").rglob("*.html"))
    missing = []
    for p in views:
        txt = p.read_text(encoding="utf-8")
        # Only check files with POST forms
        if '<form' in txt.lower() and 'method="post"' in txt.lower():
            if 'csrf_token' not in txt.lower():
                missing.append(str(p))
    assert missing == [], f"Forms missing CSRF: {missing}"

def test_csrf_rejects_without_token():
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    app.config["WTF_CSRF_TIME_LIMIT"] = None
    client = app.test_client()
    # Need a session for CSRF
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "student"
    # Try POST without token — should be 400
    resp = client.post("/student/log/add", data={"content": "test"}, follow_redirects=False)
    # Flask-WTF returns 400 on CSRF failure
    assert resp.status_code == 400, f"Expected 400 CSRF, got {resp.status_code}: {resp.data[:200]}"

def test_csrf_accepts_with_token():
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    app.config["WTF_CSRF_TIME_LIMIT"] = None
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "student"
    # Get token from login page
    resp = client.get("/login")
    assert resp.status_code == 200
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
    assert m, "CSRF token not found in login page"
    token = m.group(1)
    # Now POST with token in form — mock DB for log/add
    from unittest.mock import MagicMock, patch
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (1,)  # attendance id
    mock_conn.cursor.return_value = mock_cursor
    with patch("app.Http.Controllers.student.get_db_connection", return_value=mock_conn):
        with patch("app.Models.db.get_db_connection", return_value=mock_conn):
            resp2 = client.post("/student/log/add", data={"content": "test log", "csrf_token": token}, follow_redirects=False)
            assert resp2.status_code != 400, f"CSRF valid token should not be 400, got {resp2.status_code}"

def test_csrf_json_header():
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["role"] = "admin"
    # Get token from login page (always has CSRF)
    resp0 = client.get("/login")
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', resp0.get_data(as_text=True))
    assert m, "CSRF token not found"
    token = m.group(1)
    # JSON without token should be 400
    resp = client.post("/admin/users/students/create", json={"username": "testuser2", "email": "t@b.com", "full_name": "Test User", "program": "BSIT", "password": "Pass12345", "confirm_password": "Pass12345"}, headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 400
    # With header should not be 400 CSRF (may still be 400 for validation but not CSRF)
    resp2 = client.post("/admin/users/students/create", json={"username": "testuser2", "email": "t2@b.com", "full_name": "Test User", "program": "BSIT", "password": "Pass12345", "confirm_password": "Pass12345"}, headers={"X-Requested-With": "XMLHttpRequest", "X-CSRFToken": token})
    assert resp2.status_code != 400 or b"CSRF" not in resp2.data

def test_csrf_enabled_config():
    from bootstrap.app import app
    assert app.config["WTF_CSRF_ENABLED"] is True
    assert app.config["WTF_CSRF_TIME_LIMIT"] is None
