import os
import smtplib

from email.message import EmailMessage


def send_email(recipient, subject, body):
    smtp_host = os.environ.get(
        "SMTP_HOST",
        "smtp.gmail.com"
    )

    smtp_port = int(
        os.environ.get(
            "SMTP_PORT",
            "587"
        )
    )

    smtp_username = os.environ.get(
        "SMTP_USERNAME",
        ""
    ).strip()

    smtp_password = os.environ.get(
        "SMTP_PASSWORD",
        ""
    ).replace(" ", "")

    email_from = os.environ.get(
        "EMAIL_FROM",
        smtp_username
    ).strip()

    if not smtp_username or not smtp_password:
        raise RuntimeError(
            "SMTP email credentials are not configured."
        )

    if not recipient:
        raise ValueError(
            "Recipient email address is required."
        )

    message = EmailMessage()

    message["From"] = email_from
    message["To"] = recipient
    message["Subject"] = subject

    message.set_content(body)

    with smtplib.SMTP(
        smtp_host,
        smtp_port,
        timeout=30
    ) as server:

        server.ehlo()

        server.starttls()

        server.ehlo()

        server.login(
            smtp_username,
            smtp_password
        )

        server.send_message(message)


def send_password_reset_email(
    recipient,
    username,
    reset_url
):
    subject = "Reset your Nexora password"

    body = f"""Hello {username},

We received a request to reset your Nexora password.

Use the secure link below to create a new password:

{reset_url}

This password reset link expires in 30 minutes and can only be used once.

If you did not request this password reset, you can safely ignore this email.

Nexora
"""

    send_email(
        recipient,
        subject,
        body
    )


def send_password_changed_email(
    recipient,
    username
):
    subject = "Your Nexora password was changed"

    body = f"""Hello {username},

Your Nexora account password was successfully changed.

If you made this change, no further action is required.

If you did not change your password, contact your Nexora administrator immediately.

Nexora
"""

    send_email(
        recipient,
        subject,
        body
    )