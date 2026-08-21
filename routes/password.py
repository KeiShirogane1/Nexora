import os

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from database.db import get_db_connection

from routes.security import (
    hash_password,
    verify_password,
    login_required,
)

from services.email_service import (
    send_password_reset_email,
    send_password_changed_email,
)

from services.password_reset_service import (
    create_reset_token,
    get_valid_reset_token,
    mark_reset_token_used,
    invalidate_user_reset_tokens,
)


password = Blueprint(
    "password",
    __name__
)