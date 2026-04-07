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
    draft_id: int | None = None,
) -> bool:
    """
    Send an AI-generated draft reply back to the person who forwarded the email.

    Includes:
    - A "Send Reply" button that sends a threaded reply directly to the guest
    - A mailto: link as fallback to open a pre-composed reply
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
        draft_id:          DraftReply ID for the one-click send endpoint.

    Returns:
        True if SendGrid accepted the message (2xx), False otherwise.
    """
    settings = get_settings()
    intent_label = ", ".join(intents).title() if intents else "General Inquiry"
    ts = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")

    subject = f"[Draft Ready] Re: {original_subject}"

    # Build mailto: link for one-click reply
    mailto_link = _build_mailto_link(guest_email, original_subject, draft_text)

    # Build feedback URLs and send-reply URL
    base = settings.base_url.rstrip("/")
    feedback_perfect = None
    feedback_changed = None
    if feedback_token:
        feedback_perfect = f"{base}/api/feedback/{feedback_token}/perfect"
        feedback_changed = f"{base}/api/feedback/{feedback_token}/changed"

    send_reply_url = None
    if draft_id:
        send_reply_url = f"{base}/api/draft/{draft_id}/send"

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
        send_reply_url=send_reply_url,
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


def send_reply_to_guest(
    guest_email: str,
    guest_name: str,
    original_subject: str,
    original_message_id: str,
    draft_text: str,
    from_email: str,
    from_name: str = "Park Hyatt Aviara",
) -> bool:
    """
    Send the AI-generated draft directly to the guest as a threaded reply.

    Uses In-Reply-To and References headers so the reply appears in the
    guest's inbox as part of the original email conversation.

    Args:
        guest_email:         The guest's email address.
        guest_name:          The guest's display name.
        original_subject:    Subject line of the original email.
        original_message_id: Message-ID of the original inbound email (for threading).
        draft_text:          The AI-generated reply text.
        from_email:          The stream's inbound email (e.g. concierge@aviara.preshift.app).
        from_name:           Display name for the From field.

    Returns:
        True if SendGrid accepted the message (2xx), False otherwise.
    """
    settings = get_settings()

    reply_subject = f"Re: {original_subject}" if not original_subject.lower().startswith("re:") else original_subject

    # Build a clean HTML version of the draft text
    draft_html = (
        draft_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )

    html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Georgia, serif; color: #1a1a1a; max-width: 680px; margin: 0 auto; padding: 24px; line-height: 1.7;">
{draft_html}
</body>
</html>"""

    payload = {
        "personalizations": [{"to": [{"email": guest_email, "name": guest_name}]}],
        "from": {"email": from_email, "name": from_name},
        "subject": reply_subject,
        "content": [
            {"type": "text/plain", "value": draft_text},
            {"type": "text/html", "value": html_body},
        ],
        "headers": {
            "In-Reply-To": original_message_id,
            "References": original_message_id,
        },
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
            "Threaded reply sent to guest %r <%s> | subject=%r | from=%s",
            guest_name, guest_email, reply_subject, from_email,
        )
        return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "SendGrid rejected guest reply: %s — %s",
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except httpx.RequestError as exc:
        logger.error("Network error sending guest reply via SendGrid: %s", exc)
        return False