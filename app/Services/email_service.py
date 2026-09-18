import json
import os
import urllib.error
import urllib.request


BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_email(recipient, subject, body, html_body=None):
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

    if html_body:
        payload["htmlContent"] = html_body

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

def send_profile_updated_email(
    recipient,
    username,
    changed_by="Administrator"
):

    subject = "Your Nexora profile was updated"

    body = f"""
Hello {username},


Your Nexora student profile information has been updated by the administrator.


Updated by:
{changed_by}


If you did not expect this change, please contact the Nexora administrator.


Nexora System
""".strip()

    send_email(
        recipient,
        subject,
        body
    )



def send_account_request_email(
    recipient,
    admin_username,
    pending_user_id,
    username,
    email,
    account_type,
    review_url,
    auto_minutes=5,
):
    account_label = account_type.title()
    subject = f"New Nexora Account Request — {account_label}"

    body = f"""
Hello {admin_username or "Administrator"},

A new Nexora account is waiting for approval.

Username: {username}
Email: {email}
Account Type: {account_label}

If no administrator action is taken, this account will be approved automatically after {auto_minutes} minutes.

Review and approve the user:
{review_url}

Nexora System
""".strip()

    safe_review_url = (
        review_url.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    safe_username = (
        username.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    safe_email = (
        email.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    html_body = f"""
<div style="font-family:Arial,Helvetica,sans-serif;background:#f8fafc;padding:28px;color:#0f172a;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:16px;padding:28px;">
    <div style="font-size:12px;font-weight:800;letter-spacing:.12em;color:#f45125;">NEXORA ACCOUNT APPROVAL</div>
    <h2 style="margin:10px 0 8px;font-size:24px;">New account request</h2>
    <p style="margin:0 0 20px;color:#64748b;line-height:1.6;">
      A new {account_label.lower()} account is waiting for approval. If no action is taken, Nexora will approve it automatically after {auto_minutes} minutes.
    </p>
    <div style="background:#fff8f5;border:1px solid #ffe0d5;border-radius:12px;padding:16px;margin-bottom:20px;">
      <p style="margin:0 0 8px;"><strong>Username:</strong> {safe_username}</p>
      <p style="margin:0 0 8px;"><strong>Email:</strong> {safe_email}</p>
      <p style="margin:0;"><strong>Account Type:</strong> {account_label}</p>
    </div>
    <a href="{safe_review_url}" style="display:inline-block;padding:12px 18px;border-radius:10px;background:#f45125;color:#ffffff;text-decoration:none;font-weight:800;">
      Review &amp; Approve User
    </a>
    <p style="margin:18px 0 0;color:#94a3b8;font-size:12px;line-height:1.5;">
      For security, the button opens the protected Admin User Management page. Admin authentication is still required.
    </p>
  </div>
</div>
""".strip()

    send_email(
        recipient,
        subject,
        body,
        html_body=html_body,
    )


def send_account_approved_email(
    recipient,
    username,
    account_type,
    automatic=False,
):
    account_label = "student" if account_type == "student" else "supervisor"
    base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    login_url = f"{base_url}/login" if base_url else ""

    approval_note = (
        "Your account was approved automatically after the 5-minute approval window."
        if automatic
        else "Your account was approved by a Nexora administrator."
    )

    next_step = (
        "You may now sign in and complete your student profile."
        if account_label == "student"
        else "You may now sign in to your Nexora supervisor workspace."
    )

    body = f"""
Hello {username},

Your Nexora {account_label} account has been approved.

{approval_note}

{next_step}
{login_url}

Welcome to Nexora.

Nexora System
""".strip()

    send_email(
        recipient,
        "Nexora Account Approved",
        body,
    )


def send_account_rejected_email(
    recipient,
    username,
    account_type,
):
    body = f"""
Hello {username},

Your Nexora {account_type} account request was not approved.

Please contact the Nexora administrator for more information.

Nexora System
""".strip()

    send_email(
        recipient,
        "Nexora Account Request Cancelled",
        body,
    )
