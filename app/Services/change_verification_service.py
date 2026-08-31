import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from app.Models.db import get_db_connection

CHANGE_CODE_MINUTES = 10
MAX_ATTEMPTS = 5

def hash_code(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()

def create_change_code(user_id):
    # 6-digit numeric code, secrets
    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = hash_code(code)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=CHANGE_CODE_MINUTES)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Invalidate previous unused codes for this user
        cursor.execute(
            "UPDATE change_verification_codes SET used_at = CURRENT_TIMESTAMP WHERE user_id = ? AND used_at IS NULL",
            (user_id,)
        )
        cursor.execute(
            "INSERT INTO change_verification_codes (user_id, code_hash, expires_at, attempts) VALUES (?, ?, ?, 0)",
            (user_id, code_hash, expires_at)
        )
        conn.commit()
        return code
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def verify_change_code(user_id, code):
    if not code or not code.strip():
        return False, "Code is required."
    code_hash = hash_code(code.strip())
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, code_hash, expires_at, used_at, attempts
            FROM change_verification_codes
            WHERE user_id = ?
              AND used_at IS NULL
              AND expires_at > CURRENT_TIMESTAMP
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return False, "No valid code found. Please request a new code."
        # row may be HybridRow or sqlite Row
        try:
            attempts = row["attempts"] if "attempts" in row.keys() else row[4]
            stored_hash = row["code_hash"] if "code_hash" in row.keys() else row[1]
            row_id = row["id"] if "id" in row.keys() else row[0]
        except:
            attempts = row[4]
            stored_hash = row[1]
            row_id = row[0]
        if attempts >= MAX_ATTEMPTS:
            # mark as used to prevent brute force and force new code
            cursor.execute("UPDATE change_verification_codes SET used_at = CURRENT_TIMESTAMP WHERE id = ?", (row_id,))
            conn.commit()
            return False, "Too many attempts. Please request a new code."
        if stored_hash != code_hash:
            # increment attempts
            cursor.execute("UPDATE change_verification_codes SET attempts = attempts + 1 WHERE id = ?", (row_id,))
            conn.commit()
            remaining = MAX_ATTEMPTS - (attempts + 1)
            if remaining <= 0:
                cursor.execute("UPDATE change_verification_codes SET used_at = CURRENT_TIMESTAMP WHERE id = ?", (row_id,))
                conn.commit()
                return False, "Too many attempts. Please request a new code."
            return False, f"Invalid code. {remaining} attempts remaining."
        # success - mark used
        cursor.execute("UPDATE change_verification_codes SET used_at = CURRENT_TIMESTAMP WHERE id = ?", (row_id,))
        conn.commit()
        return True, None
    finally:
        cursor.close()
        conn.close()

def has_pending_code(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM change_verification_codes WHERE user_id = ? AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP LIMIT 1",
            (user_id,)
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()

def invalidate_user_codes(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE change_verification_codes SET used_at = CURRENT_TIMESTAMP WHERE user_id = ? AND used_at IS NULL", (user_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()
