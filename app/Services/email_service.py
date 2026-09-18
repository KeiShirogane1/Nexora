import html
import json
import os
import urllib.error
import urllib.request


BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


EMAIL_THEMES = {
    "default": {
        "accent": "#2563eb",
        "soft": "#eff6ff",
        "label": "NEXORA UPDATE",
        "icon": "N",
    },
    "password_reset": {
        "accent": "#2563eb",
        "soft": "#eff6ff",
        "label": "SECURE PASSWORD RESET",
        "icon": "↻",
    },
    "password_changed": {
        "accent": "#0f766e",
        "soft": "#f0fdfa",
        "label": "SECURITY CONFIRMATION",
        "icon": "✓",
    },
    "verification": {
        "accent": "#7c3aed",
        "soft": "#f5f3ff",
        "label": "SECURITY VERIFICATION",
        "icon": "#",
    },
    "temporary_password": {
        "accent": "#d97706",
        "soft": "#fff7ed",
        "label": "TEMPORARY ACCESS",
        "icon": "!",
    },
    "profile": {
        "accent": "#0284c7",
        "soft": "#f0f9ff",
        "label": "PROFILE UPDATE",
        "icon": "P",
    },
    "account_request": {
        "accent": "#f45125",
        "soft": "#fff3ee",
        "label": "ACCOUNT APPROVAL",
        "icon": "⌛",
    },
    "approved": {
        "accent": "#059669",
        "soft": "#ecfdf5",
        "label": "GOOD NEWS",
        "icon": "✓",
    },
    "rejected": {
        "accent": "#dc2626",
        "soft": "#fef2f2",
        "label": "ACCOUNT UPDATE",
        "icon": "×",
    },
    "activated": {
        "accent": "#16a34a",
        "soft": "#f0fdf4",
        "label": "ACCESS RESTORED",
        "icon": "✓",
    },
    "deactivated": {
        "accent": "#dc2626",
        "soft": "#fef2f2",
        "label": "ACCESS UPDATE",
        "icon": "!",
    },
}


def _safe(value):
    return html.escape(str(value or ""), quote=True)


def _base_url():
    return os.environ.get("APP_BASE_URL", "").strip().rstrip("/")


def _theme_for_subject(subject):
    text = (subject or "").lower()

    if "verification code" in text:
        return "verification"
    if "temporary password" in text:
        return "temporary_password"
    if "reset" in text and "password" in text:
        return "password_reset"
    if "password" in text and ("changed" in text or "updated" in text):
        return "password_changed"
    if "profile" in text and ("updated" in text or "changed" in text):
        return "profile"
    if "account request" in text and ("cancel" in text or "reject" in text):
        return "rejected"
    if "account request" in text or "approval" in text:
        return "account_request"
    if "approved" in text:
        return "approved"
    if "deactivated" in text:
        return "deactivated"
    if "activated" in text:
        return "activated"

    return "default"


def _plain_text_to_html(body):
    lines = [line.rstrip() for line in str(body or "").strip().splitlines()]

    while lines and not lines[-1].strip():
        lines.pop()

    if lines and lines[-1].strip().lower() == "nexora system":
        lines.pop()

    paragraphs = []
    current = []

    for line in lines:
        if not line.strip():
            if current:
                paragraphs.append("<br>".join(_safe(item) for item in current))
                current = []
            continue
        current.append(line.strip())

    if current:
        paragraphs.append("<br>".join(_safe(item) for item in current))

    if not paragraphs:
        return "<p style=\"margin:0;color:#53657d;line-height:1.7;\">Nexora notification.</p>"

    return "".join(
        f'<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">{paragraph}</p>'
        for paragraph in paragraphs
    )


def _details_table(details, theme):
    if not details:
        return ""

    rows = []
    for label, value in details:
        rows.append(
            f"""
            <tr>
              <td style="padding:7px 0;color:#7b8798;font-size:13px;vertical-align:top;width:38%;">{_safe(label)}</td>
              <td style="padding:7px 0;color:#172033;font-size:13px;font-weight:700;vertical-align:top;">{_safe(value)}</td>
            </tr>
            """
        )

    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
           style="margin:20px 0;border-collapse:separate;border-spacing:0;background:{theme['soft']};border:1px solid {theme['accent']}22;border-radius:14px;">
      <tr>
        <td style="padding:14px 16px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
            {''.join(rows)}
          </table>
        </td>
      </tr>
    </table>
    """


def _render_nexora_email(
    *,
    title,
    body_html,
    theme_key="default",
    preheader="",
    greeting=None,
    action_url=None,
    action_label=None,
    details=None,
    note_title=None,
    note_body=None,
    footer_note=None,
):
    theme = EMAIL_THEMES.get(theme_key, EMAIL_THEMES["default"])
    action_html = ""
    note_html = ""
    greeting_html = ""
    details_html = _details_table(details, theme)

    if greeting:
        greeting_html = (
            f'<p style="margin:0 0 14px;color:#172033;font-size:15px;font-weight:700;">'
            f'Hello {_safe(greeting)},</p>'
        )

    if action_url and action_label:
        safe_url = _safe(action_url)
        action_html = f"""
        <table role="presentation" cellspacing="0" cellpadding="0" style="margin:22px 0 18px;">
          <tr>
            <td bgcolor="{theme['accent']}" style="border-radius:10px;">
              <a href="{safe_url}"
                 style="display:inline-block;padding:13px 22px;color:#ffffff;text-decoration:none;font-size:14px;font-weight:800;line-height:1;">
                {_safe(action_label)} &nbsp;→
              </a>
            </td>
          </tr>
        </table>
        <p style="margin:0 0 18px;color:#8a97a8;font-size:11px;line-height:1.55;">
          If the button does not work, copy and paste this link into your browser:<br>
          <a href="{safe_url}" style="color:{theme['accent']};word-break:break-all;">{safe_url}</a>
        </p>
        """

    if note_title or note_body:
        note_html = f"""
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
               style="margin:18px 0 0;border-collapse:separate;border-spacing:0;background:#f8fafc;border:1px solid #e7edf4;border-radius:12px;">
          <tr>
            <td style="padding:14px 16px;">
              {f'<div style="margin:0 0 4px;color:#24364d;font-size:12px;font-weight:800;">{_safe(note_title)}</div>' if note_title else ''}
              {f'<div style="color:#718096;font-size:12px;line-height:1.55;">{_safe(note_body)}</div>' if note_body else ''}
            </td>
          </tr>
        </table>
        """

    footer_copy = footer_note or "This is an automated message from Nexora. Please keep your account information secure."

    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f4f7fa;font-family:Arial,Helvetica,sans-serif;color:#172033;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{_safe(preheader or title)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f7fa;padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                 style="max-width:600px;background:#ffffff;border:1px solid #e4eaf1;border-radius:18px;overflow:hidden;">
            <tr>
              <td style="padding:22px 28px;border-bottom:1px solid #edf1f5;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td style="vertical-align:middle;">
                      <table role="presentation" cellspacing="0" cellpadding="0">
                        <tr>
                          <td style="width:38px;height:38px;border-radius:10px;background:#eaf3ff;color:#1269d3;text-align:center;font-size:20px;font-weight:900;">N</td>
                          <td style="padding-left:10px;">
                            <div style="color:#0f1f38;font-size:22px;font-weight:900;letter-spacing:-.02em;">Nexora</div>
                            <div style="margin-top:2px;color:#8b98a9;font-size:10px;letter-spacing:.04em;">INTERNSHIP MONITORING &amp; EVALUATION</div>
                          </td>
                        </tr>
                      </table>
                    </td>
                    <td align="right" style="color:#a0aaba;font-size:10px;vertical-align:middle;">People • Progress • Performance</td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="padding:30px 28px 28px;">
                <div style="width:58px;height:58px;border-radius:18px;background:{theme['soft']};color:{theme['accent']};font-size:28px;font-weight:900;line-height:58px;text-align:center;">{_safe(theme['icon'])}</div>
                <div style="margin-top:20px;color:{theme['accent']};font-size:11px;font-weight:900;letter-spacing:.12em;">{_safe(theme['label'])}</div>
                <h1 style="margin:7px 0 18px;color:#10213a;font-size:28px;line-height:1.18;letter-spacing:-.02em;">{_safe(title)}</h1>

                {greeting_html}
                {body_html}
                {details_html}
                {action_html}
                {note_html}
              </td>
            </tr>

            <tr>
              <td style="padding:18px 28px 22px;border-top:1px solid #edf1f5;background:#fbfcfd;text-align:center;">
                <div style="color:#22334c;font-size:12px;font-weight:800;">Nexora System</div>
                <div style="margin-top:5px;color:#95a1b0;font-size:10px;line-height:1.5;">{_safe(footer_copy)}</div>
                <div style="margin-top:8px;color:#b1bac6;font-size:9px;">Learning today. A brighter tomorrow.</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


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

    if not html_body:
        theme_key = _theme_for_subject(subject)
        html_body = _render_nexora_email(
            title=subject,
            body_html=_plain_text_to_html(body),
            theme_key=theme_key,
            preheader=subject,
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
        "textContent": body,
        "htmlContent": html_body,
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

    html_body = _render_nexora_email(
        title="Reset your password",
        greeting=username,
        theme_key="password_reset",
        preheader="Use your secure Nexora password reset link.",
        body_html="""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  We received a request to reset your Nexora password. Use the secure button below to create a new password.
</p>
""",
        action_url=reset_url,
        action_label="Reset Password",
        note_title="Didn’t request this?",
        note_body="You can safely ignore this email. Your password will not change unless the reset link is used.",
        footer_note="Password reset links expire for your security and should never be shared.",
    )

    send_email(
        recipient,
        subject,
        body,
        html_body=html_body,
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

    html_body = _render_nexora_email(
        title="Password changed successfully",
        greeting=username,
        theme_key="password_changed",
        preheader="Your Nexora password has been updated.",
        body_html="""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  Your Nexora account password was changed successfully. If you made this change, no further action is required.
</p>
""",
        note_title="Wasn’t you?",
        note_body="Contact the Nexora administrator immediately if you did not make this password change.",
        footer_note="Nexora will never ask you to send your password by email.",
    )

    send_email(
        recipient,
        subject,
        body,
        html_body=html_body,
    )


def send_change_password_code_email(
    recipient,
    username,
    code,
):
    subject = "Nexora — Change Password Verification Code"

    body = f"""
Hello {username},

You requested to change your Nexora password.

Your verification code is:

{code}

This code expires in 10 minutes and can only be used once.
If you did not request this, please ignore this email.

Nexora System
""".strip()

    safe_code = _safe(code)
    html_body = _render_nexora_email(
        title="Verify your password change",
        greeting=username,
        theme_key="verification",
        preheader="Your Nexora verification code expires in 10 minutes.",
        body_html=f"""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  Use the verification code below to continue changing your password.
</p>
<div style="margin:20px 0;padding:18px 20px;border-radius:14px;background:#f5f3ff;border:1px solid #ddd6fe;text-align:center;">
  <div style="color:#8b7aaa;font-size:10px;font-weight:800;letter-spacing:.12em;">VERIFICATION CODE</div>
  <div style="margin-top:7px;color:#5b21b6;font-size:32px;font-weight:900;letter-spacing:.18em;font-family:Arial,Helvetica,sans-serif;">{safe_code}</div>
</div>
""",
        note_title="Code expires in 10 minutes",
        note_body="This code can only be used once. Ignore this email if you did not request a password change.",
        footer_note="Never share a verification code with anyone, including someone claiming to be Nexora support.",
    )

    send_email(
        recipient,
        subject,
        body,
        html_body=html_body,
    )


def send_temporary_password_email(
    recipient,
    username,
    temporary_password,
):
    subject = "Nexora Temporary Password"

    body = f"""
Hello {username},

Your Nexora account password has been reset by the administrator.

Your temporary password is:

{temporary_password}

Please login and change your password after signing in.

Nexora System
""".strip()

    safe_password = _safe(temporary_password)
    login_url = f"{_base_url()}/login" if _base_url() else None

    html_body = _render_nexora_email(
        title="Temporary password issued",
        greeting=username,
        theme_key="temporary_password",
        preheader="An administrator reset your Nexora password.",
        body_html=f"""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  A Nexora administrator reset your account password. Use this temporary password to sign in:
</p>
<div style="margin:20px 0;padding:18px 20px;border-radius:14px;background:#fff7ed;border:1px solid #fed7aa;text-align:center;">
  <div style="color:#a56a18;font-size:10px;font-weight:800;letter-spacing:.12em;">TEMPORARY PASSWORD</div>
  <div style="margin-top:7px;color:#9a4f0c;font-size:24px;font-weight:900;letter-spacing:.08em;font-family:Arial,Helvetica,sans-serif;">{safe_password}</div>
</div>
""",
        action_url=login_url,
        action_label="Login to Nexora" if login_url else None,
        note_title="Change it after signing in",
        note_body="For your security, replace this temporary password with a password only you know.",
        footer_note="Do not forward this email or share the temporary password.",
    )

    send_email(
        recipient,
        subject,
        body,
        html_body=html_body,
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

    html_body = _render_nexora_email(
        title="Your profile was updated",
        greeting=username,
        theme_key="profile",
        preheader="Your Nexora student profile information was updated.",
        body_html="""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  Your Nexora student profile information has been updated.
</p>
""",
        details=[("Updated by", changed_by)],
        note_title="Unexpected change?",
        note_body="Contact the Nexora administrator if you did not expect this profile update.",
        footer_note="Profile updates help keep your internship records accurate and current.",
    )

    send_email(
        recipient,
        subject,
        body,
        html_body=html_body,
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

    html_body = _render_nexora_email(
        title="New account request",
        greeting=admin_username or "Administrator",
        theme_key="account_request",
        preheader=f"{username} requested a Nexora {account_label.lower()} account.",
        body_html=f"""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  A new { _safe(account_label.lower()) } account is waiting for your review. If no Admin action is taken, Nexora will approve the account automatically after <strong style="color:#172033;">{int(auto_minutes)} minutes</strong>.
</p>
""",
        details=[
            ("Username", username),
            ("Email", email),
            ("Account Type", account_label),
            ("Automatic Approval", f"{auto_minutes} minutes"),
        ],
        action_url=review_url,
        action_label="Review & Approve User",
        note_title="Protected Admin action",
        note_body="The review button opens User Management. Admin authentication and CSRF protection are still required before approval.",
        footer_note="Review pending accounts promptly when manual verification is needed.",
    )

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
    login_url = f"{_base_url()}/login" if _base_url() else None

    approval_note = (
        "Your account was approved automatically after the 5-minute approval window."
        if automatic
        else "Your account was approved by a Nexora administrator."
    )

    next_step = (
        "You can now sign in and complete your Student Profile."
        if account_label == "student"
        else "You can now sign in to your Supervisor workspace."
    )

    body = f"""
Hello {username},

Your Nexora {account_label} account has been approved.

{approval_note}

{next_step}
{login_url or ""}

Welcome to Nexora.

Nexora System
""".strip()

    html_body = _render_nexora_email(
        title="Account approved",
        greeting=username,
        theme_key="approved",
        preheader="Your Nexora account is ready.",
        body_html=f"""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  Your Nexora <strong style="color:#172033;">{_safe(account_label)}</strong> account has been approved.
</p>
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  {_safe(approval_note)} {_safe(next_step)}
</p>
""",
        action_url=login_url,
        action_label="Login to Nexora" if login_url else None,
        note_title="Ready to get started?",
        note_body="Your Nexora workspace is now available with the permissions for your approved account type.",
        footer_note="Welcome to Nexora — your internship workspace for progress, feedback, and performance.",
    )

    send_email(
        recipient,
        "Nexora Account Approved",
        body,
        html_body=html_body,
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

    html_body = _render_nexora_email(
        title="Account request cancelled",
        greeting=username,
        theme_key="rejected",
        preheader="An update about your Nexora account request.",
        body_html=f"""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  Your Nexora <strong style="color:#172033;">{_safe(account_type)}</strong> account request was not approved.
</p>
""",
        note_title="Need more information?",
        note_body="Please contact the Nexora administrator if you believe the request should be reviewed again.",
        footer_note="This message confirms the current status of your Nexora account request.",
    )

    send_email(
        recipient,
        "Nexora Account Request Cancelled",
        body,
        html_body=html_body,
    )


def send_account_status_email(
    recipient,
    username,
    account_type,
    active,
):
    account_label = account_type.title()
    login_url = f"{_base_url()}/login" if _base_url() and active else None

    if active:
        subject = "Nexora Account Activated"
        title = "Account access restored"
        body_line = f"Your Nexora {account_type} account has been activated. You may now sign in and continue using Nexora."
        theme_key = "activated"
        note_title = "Welcome back"
        note_body = "Your account access is active again."
    else:
        subject = "Nexora Account Deactivated"
        title = "Account access deactivated"
        body_line = f"Your Nexora {account_type} account has been deactivated by the administrator."
        theme_key = "deactivated"
        note_title = "Need help?"
        note_body = "Contact the Nexora administrator if you believe your account was deactivated by mistake."

    body = f"""
Hello {username},

{body_line}

Nexora System
""".strip()

    html_body = _render_nexora_email(
        title=title,
        greeting=username,
        theme_key=theme_key,
        preheader=body_line,
        body_html=f"""
<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">
  {_safe(body_line)}
</p>
""",
        details=[("Account Type", account_label), ("Access Status", "Active" if active else "Deactivated")],
        action_url=login_url,
        action_label="Login to Nexora" if login_url else None,
        note_title=note_title,
        note_body=note_body,
        footer_note="Account access is managed by your Nexora administrator.",
    )

    send_email(
        recipient,
        subject,
        body,
        html_body=html_body,
    )



def send_account_appeal_access_email(recipient,username,account_type,action_type,deadline_display,appeal_url):
    action_label="moved to Trash" if action_type=="deleted" else "deactivated"
    subject="Nexora Account Action — 24-Hour Appeal Available"
    body=f"""Hello {username},

Your Nexora {account_type.lower()} account has been {action_label}.
You have 24 hours to submit an appeal before permanent account removal.

Appeal deadline: {deadline_display}
Submit an appeal: {appeal_url}

Use the same registered Nexora account credentials.

Nexora System"""
    html_body=_render_nexora_email(
        title="Your account is inactive",greeting=username,theme_key="deactivated",
        preheader="You have 24 hours to appeal this Nexora account action.",
        body_html=f'<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">Your Nexora <strong>{_safe(account_type.lower())}</strong> account has been {_safe(action_label)}. You have <strong>24 hours</strong> to submit an appeal.</p>',
        details=[("Account Type",account_type),("Appeal Deadline",deadline_display)],
        action_url=appeal_url,action_label="Submit an Appeal",
        note_title="Account verification required",
        note_body="Use the same username/email and password registered to this inactive account. Submitting an appeal pauses permanent removal.",
        footer_note="Required academic records may be retained in anonymized form after permanent account removal.",
    )
    send_email(recipient,subject,body,html_body=html_body)


def send_appeal_received_email(recipient,username,account_type):
    subject="Nexora Account Appeal Received"
    body=f"Hello {username},\n\nYour Nexora {account_type.lower()} account appeal has been received. Permanent removal is paused while an administrator reviews it.\n\nNexora System"
    html_body=_render_nexora_email(
        title="Appeal received",greeting=username,theme_key="default",
        body_html='<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">Your appeal has been received. Permanent removal is paused while the Nexora administrator reviews your request.</p>',
        note_title="Access remains disabled during review",note_body="You will receive another email when the administrator makes a decision.",
    )
    send_email(recipient,subject,body,html_body=html_body)


def send_admin_appeal_submitted_email(recipient,admin_username,username,email,account_type,reason,review_url):
    subject=f"New Nexora Account Appeal — {username}"
    body=f"Hello {admin_username or 'Administrator'},\n\n{username} ({email}) submitted a {account_type} account appeal.\n\nReason:\n{reason}\n\nReview: {review_url}\n\nNexora System"
    html_body=_render_nexora_email(
        title="New account appeal",greeting=admin_username or "Administrator",theme_key="account_request",
        body_html='<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">A deactivated Nexora account submitted an appeal. Automatic permanent removal is paused until your decision.</p>',
        details=[("Username",username),("Email",email),("Account Type",account_type)],
        action_url=review_url,action_label="Review Appeal",note_title="Appeal reason",note_body=reason,
    )
    send_email(recipient,subject,body,html_body=html_body)


def send_account_appeal_decision_email(recipient,username,account_type,approved):
    if approved:
        subject="Nexora Account Appeal Approved";title="Your appeal was approved";theme="approved";copy="Your Nexora account has been reactivated. You may sign in again.";url=f"{_base_url()}/login" if _base_url() else None;label="Login to Nexora"
    else:
        subject="Nexora Account Appeal Denied";title="Your appeal was not approved";theme="rejected";copy="The administrator denied your appeal. Your account login identity will be permanently removed.";url=None;label=None
    body=f"Hello {username},\n\n{copy}\n\nNexora System"
    html_body=_render_nexora_email(title=title,greeting=username,theme_key=theme,body_html=f'<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">{_safe(copy)}</p>',action_url=url,action_label=label,footer_note="Required academic or internship history may be retained in anonymized form.")
    send_email(recipient,subject,body,html_body=html_body)


def send_account_removed_email(recipient,username,account_type,removal_reason):
    reason="The 24-hour appeal window expired without a submitted appeal." if removal_reason=="appeal_window_expired" else ("The Nexora administrator permanently removed the account identity." if removal_reason=="administrator_permanent_removal" else "The account appeal was denied.")
    subject="Nexora Account Permanently Removed"
    body=f"Hello {username},\n\nYour Nexora {account_type.lower()} account login identity has been permanently removed.\n\n{reason}\n\nNexora System"
    html_body=_render_nexora_email(title="Account identity removed",greeting=username,theme_key="rejected",body_html=f'<p style="margin:0 0 14px;color:#53657d;font-size:15px;line-height:1.7;">Your Nexora <strong>{_safe(account_type.lower())}</strong> account login identity has been permanently removed.</p>',note_title="Reason",note_body=reason,footer_note="Required academic and internship history may be retained in anonymized form for institutional records.")
    send_email(recipient,subject,body,html_body=html_body)
