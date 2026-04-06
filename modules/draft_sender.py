"""
draft_sender.py — Send AI-generated draft replies back to the forwarder via SendGrid.

Flow: Staff forward any email → Claude drafts a reply → Draft lands in forwarder's inbox.
The forwarder reviews it, pastes into a reply to the original sender, and hits send.
"""

import logging
from datetime import datetime, timezone

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def send_draft_to_staff(
    staff_email: str,
    guest_name: str,
    guest_email: str,
    original_subject: str,
    draft_text: str,
    hotel_name: str,
    intents: list[str],
    feedback_token: str | None = None,
) -> bool:
    """
    Send an AI-generated draft reply back to the person who forwarded the email.

    Includes:
    - A mailto: link to open a pre-composed reply to the guest (one click)
    - One-click feedback buttons ("This was perfect" / "This needed changes")

    Args:
        staff_email:       The forwarder's email address (reply destination).
        guest_name:        Display name of the original sender.
        guest_email:       Email address of the original sender.
        original_subject:  Subject line of the original email.
        draft_text:        The AI-generated reply draft.
        hotel_name:        Hotel/organization name for context.
        intents:           Classified intents for the staff's reference.
        feedback_token:    Unique token for one-click feedback links.

    Returns:
        True if SendGrid accepted the message (2xx), False otherwise.
    """
    settings = get_settings()
    intent_label = ", ".join(intents).title() if intents else "General Inquiry"
    ts = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

    subject = f"[Draft Ready] Re: {original_subject}"

    # Build mailto: link for one-click reply
    mailto_link = _build_mailto_link(guest_email, original_subject, draft_text)

    # Build feedback URLs
    feedback_perfect = None
    feedback_changed = None
    if feedback_token:
        base = settings.base_url.rstrip("/")
        feedback_perfect = f"{base}/api/feedback/{feedback_token}/perfect"
        feedback_changed = f"{base}/api/feedback/{feedback_token}/changed"

    plain_body = _build_plain_body(
        guest_name=guest_name,
        guest_email=guest_email,
        original_subject=original_subject,
        draft_text=draft_text,
        hotel_name=hotel_name,
        intent_label=intent_label,
        ts=ts,
    )

    html_body = _build_html_body(
        guest_name=guest_name,
        guest_email=guest_email,
        original_subject=original_subject,
        draft_text=draft_text,
        hotel_name=hotel_name,
        intent_label=intent_label,
        ts=ts,
        mailto_link=mailto_link,
        feedback_perfect_url=feedback_perfect,
        feedback_changed_url=feedback_changed,
    )

    payload = {
        "personalizations": [{"to": [{"email": staff_email}]}],
        "from": {"email": settings.sendgrid_from_email, "name": "Ready Concierge"},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain_body},
            {"type": "text/html", "value": html_body},
        ],
        "headers": {"X-Ready-Concierge": "draft-reply"},
    }

    try:
        resp = httpx.post(
            _SENDGRID_API_URL,
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        logger.info(
            "Draft sent to forwarder %r (original sender: %r) via SendGrid",
            staff_email,
            guest_email,
        )
        return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "SendGrid rejected draft send: %s — %s",
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except httpx.RequestError as exc:
        logger.error("Network error sending draft via SendGrid: %s", exc)
        return False


def _build_mailto_link(guest_email: str, subject: str, draft_text: str) -> str:
    """Build a mailto: link that opens a pre-composed reply to the guest."""
    from urllib.parse import quote

    reply_subject = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
    return f"mailto:{quote(guest_email)}?subject={quote(reply_subject)}&body={quote(draft_text)}"


def _build_plain_body(
    guest_name: str,
    guest_email: str,
    original_subject: str,
    draft_text: str,
    hotel_name: str,
    intent_label: str,
    ts: str,
) -> str:
    return f"""\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
READY CONCIERGE · DRAFT REPLY READY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
From:     {guest_name} <{guest_email}>
Subject:  {original_subject}
Type:     {intent_label}
Time:     {ts}

Review the draft below, then reply to {guest_name} directly.
Do NOT reply to this email.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{draft_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Powered by Ready Concierge
"""


def _build_html_body(
    guest_name: str,
    guest_email: str,
    original_subject: str,
    draft_text: str,
    hotel_name: str,
    intent_label: str,
    ts: str,
    mailto_link: str | None = None,
    feedback_perfect_url: str | None = None,
    feedback_changed_url: str | None = None,
) -> str:
    draft_html = draft_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

    # One-click reply button
    mailto_button = ""
    if mailto_link:
        mailto_button = f"""
    <div style="text-align: center; padding: 20px 24px; background: #ffffff; border: 1px solid #e0d8cc; border-top: none;">
      <a href="{mailto_link}" style="display: inline-block; background: #0a1628; color: #c8a96e; text-decoration: none;
         padding: 14px 32px; border-radius: 6px; font-family: Arial, sans-serif; font-size: 14px; font-weight: 600;
         letter-spacing: 0.5px;">
        Reply to {_esc(guest_name)}
      </a>
      <p style="margin: 10px 0 0; font-size: 12px; color: #999;">
        Opens a pre-composed email to <strong>{_esc(guest_email)}</strong> in your email client
      </p>
    </div>"""

    # Feedback buttons
    feedback_block = ""
    if feedback_perfect_url and feedback_changed_url:
        feedback_block = f"""
    <div style="background: #f4f1eb; border: 1px solid #e0d8cc; border-top: none; padding: 16px 24px; text-align: center;">
      <p style="margin: 0 0 10px; font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px;">
        How was this draft?
      </p>
      <a href="{feedback_perfect_url}" style="display: inline-block; background: #2d6a2d; color: #ffffff; text-decoration: none;
         padding: 8px 20px; border-radius: 4px; font-family: Arial, sans-serif; font-size: 13px; font-weight: 500; margin: 0 6px;">
        This was perfect
      </a>
      <a href="{feedback_changed_url}" style="display: inline-block; background: #ffffff; color: #555; text-decoration: none;
         padding: 8px 20px; border-radius: 4px; font-family: Arial, sans-serif; font-size: 13px; font-weight: 500;
         border: 1px solid #ccc; margin: 0 6px;">
        This needed changes
      </a>
    </div>"""

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Georgia, serif; color: #1a1a1a; max-width: 680px; margin: 0 auto; padding: 24px;">

  <div style="background: #0a1628; color: #c8a96e; padding: 16px 24px; border-radius: 4px 4px 0 0;">
    <p style="margin: 0; font-size: 11px; letter-spacing: 2px; text-transform: uppercase;">
      Ready Concierge &nbsp;·&nbsp; Draft Reply Ready
    </p>
  </div>

  <div style="background: #f9f7f2; border: 1px solid #e0d8cc; border-top: none; padding: 20px 24px;">
    <table style="width: 100%; font-size: 13px; color: #555;">
      <tr><td style="padding: 2px 0; width: 80px;"><strong>From</strong></td><td>{_esc(guest_name)} &lt;{_esc(guest_email)}&gt;</td></tr>
      <tr><td style="padding: 2px 0;"><strong>Subject</strong></td><td>{_esc(original_subject)}</td></tr>
      <tr><td style="padding: 2px 0;"><strong>Type</strong></td><td>{_esc(intent_label)}</td></tr>
    </table>
  </div>

  <div style="background: #ffffff; border: 1px solid #e0d8cc; border-top: none; padding: 28px 24px; font-size: 15px; line-height: 1.7;">
    {draft_html}
  </div>
{mailto_button}
{feedback_block}

  <div style="background: #f9f7f2; border: 1px solid #e0d8cc; border-top: none; padding: 12px 24px;
              text-align: center; font-size: 11px; color: #999; border-radius: 0 0 4px 4px;">
    Powered by Ready Concierge
  </div>

</body>
</html>
"""


def _esc(text: str) -> str:
    """Minimal HTML escaping."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
