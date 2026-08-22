import json
import os
import urllib.error
import urllib.request


BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_email(recipient, subject, body):
    api_key = os.environ.get(
        "BREVO_API_KEY",
        ""
    ).strip()

    sender_email = os.environ.get(
        "BREVO_SENDER_EMAIL",
        ""
    ).strip()

    sender_name = os.environ.get(
        "BREVO_SENDER_NAME",
        "Nexora"
    ).strip()

    if not api_key:
        raise RuntimeError(
            "BREVO_API_KEY is not configured."
        )

    if not sender_email:
        raise RuntimeError(
            "BREVO_SENDER_EMAIL is not configured."
        )

    if not recipient:
        raise ValueError(
            "Recipient email is required."
        )

    payload = {
        "sender": {
            "name": sender_name,
            "email": sender_email
        },
        "to": [
            {
                "email": recipient
            }
        ],
        "subject": subject,
        "textContent": body
    }

    request_data = json.dumps(
        payload
    ).encode("utf-8")

    request = urllib.request.Request(
        BREVO_API_URL,
        data=request_data,
        method="POST"
    )

    request.add_header(
        "accept",
        "application/json"
    )

    request.add_header(
        "api-key",
        api_key
    )

    request.add_header(
        "content-type",
        "application/json"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:
            if response.status not in (200, 201, 202):
                raise RuntimeError(
                    "Brevo email request failed "
                    f"with status {response.status}."
                )

    except urllib.error.HTTPError as error:
        error_body = error.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"Brevo API error {error.code}: "
            f"{error_body}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            "Could not connect to Brevo API: "
            f"{error.reason}"
        ) from error


def send_password_reset_email(
    recipient,
    username,
    reset_url
):
    subject = "Reset your Nexora password"

    body = f"""
Hello {username},

We received a request to reset your Nexora password.

Use the link below to create a new password:

{reset_url}

This password reset link will expire soon.

If you did not request a password reset, you can ignore this email.

Nexora System
""".strip()

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

    body = f"""
Hello {username},

Your Nexora account password was changed successfully.

If you made this change, no further action is required.

If you did not change your password, contact the Nexora administrator immediately.

Nexora System
""".strip()

    send_email(
        recipient,
        subject,
        body
    )