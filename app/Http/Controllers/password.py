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

from app.Models.db import get_db_connection

from app.Http.Middleware.security import login_required

from app.Services.password_security import (
    hash_password,
    verify_password,
)

from app.Services.email_service import (
    send_password_changed_email,
    send_password_reset_email,
)

from app.Services.password_reset_service import (
    create_reset_token,
    get_valid_reset_token,
    invalidate_user_reset_tokens,
    mark_reset_token_used,
)


password = Blueprint(
    "password",
    __name__
)


def validate_new_password(value):
    if not value:
        return "Password is required."

    if len(value) < 8:
        return "Password must be at least 8 characters."

    return None


@password.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
def forgot_password():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    id,
                    username,
                    email
                FROM users
                WHERE LOWER(email) = LOWER(?)
                LIMIT 1
                """,
                (email,)
            )

            user = cursor.fetchone()

        finally:
            cursor.close()
            conn.close()

        if user and user["email"]:

            try:
                token = create_reset_token(
                    user["id"]
                )

                base_url = os.environ.get(
                    "APP_BASE_URL",
                    request.url_root.rstrip("/")
                ).rstrip("/")

                reset_url = (
                    f"{base_url}"
                    f"/reset-password/{token}"
                )

                send_password_reset_email(
                    recipient=user["email"],
                    username=user["username"],
                    reset_url=reset_url
                )

            except Exception:
                current_app.logger.exception(
                    "Unable to send password reset email."
                )

        # Always show the same response.
        # This prevents people from discovering
        # which email addresses exist in Nexora.
        flash(
            "If an account exists for that email, "
            "a password reset link has been sent."
        )

        return redirect(
            url_for(
                "password.forgot_password"
            )
        )

    return render_template(
        "auth/forgot_password.html"
    )


@password.route(
    "/reset-password/<token>",
    methods=["GET", "POST"]
)
def reset_password(token):

    reset_record = get_valid_reset_token(
        token
    )

    if not reset_record:

        return render_template(
            "auth/reset_password.html",
            invalid_token=True
        )

    if request.method == "POST":

        new_password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        error = validate_new_password(
            new_password
        )

        if error:

            flash(error)

            return render_template(
                "auth/reset_password.html",
                invalid_token=False
            )

        if new_password != confirm_password:

            flash(
                "Passwords do not match."
            )

            return render_template(
                "auth/reset_password.html",
                invalid_token=False
            )

        # Make reset links one-time-use.
        if not mark_reset_token_used(token):

            return render_template(
                "auth/reset_password.html",
                invalid_token=True
            )

        user_id = reset_record["user_id"]

        hashed_password = hash_password(
            new_password
        )

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE users
                SET
                    password = ?,
                    password_changed_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    hashed_password,
                    user_id
                )
            )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            cursor.close()
            conn.close()

        # Invalidate any other outstanding
        # reset links for this user.
        invalidate_user_reset_tokens(
            user_id
        )

        if reset_record["email"]:

            try:
                send_password_changed_email(
                    recipient=reset_record["email"],
                    username=reset_record["username"]
                )

            except Exception:
                current_app.logger.exception(
                    "Unable to send password changed email."
                )

        flash(
            "Your password has been reset. "
            "You can now log in."
        )

        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "auth/reset_password.html",
        invalid_token=False
    )


@password.route(
    "/change-password",
    methods=["GET", "POST"]
)
@login_required
def change_password():

    user_id = session["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                username,
                email,
                password
            FROM users
            WHERE id = ?
            LIMIT 1
            """,
            (user_id,)
        )

        user = cursor.fetchone()

    finally:
        cursor.close()
        conn.close()

    if not user:

        session.clear()

        return redirect(
            url_for("auth.login")
        )

    if request.method == "POST":

        current_password = request.form.get(
            "current_password",
            ""
        )

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not verify_password(
            user["password"],
            current_password
        ):

            flash(
                "Current password is incorrect."
            )

            return render_template(
                "auth/change_password.html"
            )

        error = validate_new_password(
            new_password
        )

        if error:

            flash(error)

            return render_template(
                "auth/change_password.html"
            )

        if new_password != confirm_password:

            flash(
                "New passwords do not match."
            )

            return render_template(
                "auth/change_password.html"
            )

        if verify_password(
            user["password"],
            new_password
        ):

            flash(
                "Your new password cannot be "
                "the same as your current password."
            )

            return render_template(
                "auth/change_password.html"
            )

        hashed_password = hash_password(
            new_password
        )

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE users
                SET
                    password = ?,
                    password_changed_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    hashed_password,
                    user_id
                )
            )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            cursor.close()
            conn.close()

        invalidate_user_reset_tokens(
            user_id
        )

        if user["email"]:

            try:
                send_password_changed_email(
                    recipient=user["email"],
                    username=user["username"]
                )

            except Exception:
                current_app.logger.exception(
                    "Unable to send password changed email."
                )

        # Force the user to authenticate again
        # after changing their password.
        session.clear()

        flash(
            "Password changed successfully. "
            "Please log in again."
        )

        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "auth/change_password.html"
    )