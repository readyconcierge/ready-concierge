"""
draft_sender.py â€” Send AI generated draft replies back to the forwarder via SendGrid.

Flow: Staff forward any email â†’ Claude drafts a reply â†’ Draft lands in forwarder's inbox.
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
            "SendGrid rejected draft send: %s â€” %s",
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
            "SendGrid rejected guest reply: %s â€” %s",
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except httpx.RequestError as exc:
        logger.error("Network error sending guest reply via SendGrid: %s", exc)
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
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
READY CONCIERGE Â· DRAFT REPLY READY
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
From:     {guest_name} <{guest_email}>
Subject:  {original_subject}
Type:     {intent_label}
Time:     {ts}

Review the draft below, then reply to {guest_name} directly.
Do NOT reply to this email.
â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

{draft_text}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
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
    send_reply_url: str | None = None,
    feedback_perfect_url: str | None = None,
    feedback_changed_url: str | None = None,
) -> str:
    draft_html = draft_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

    # One-click send button (threaded reply) â€” primary action
    reply_buttons = ""
    if send_reply_url:
        reply_buttons = f"""
    <div style="text-align: center; padding: 20px 24px; background: #ffffff; border: 1px solid #e0d8cc; border-top: none;">
      <a href="{send_reply_url}" style="display: inline-block; background: #0a1628; color: #c8a96e; text-decoration: none;
         padding: 14px 32px; border-radius: 6px; font-family: Arial, sans-serif; font-size: 14px; font-weight: 600;
         letter-spacing: 0.5px;">
        Send Reply to {_esc(guest_name)}
      </a>
      <p style="margin: 10px 0 0; font-size: 12px; color: #999;">
        Sends this draft directly to <strong>{_esc(guest_email)}</strong> as a threaded reply
      </p>"""
        if mailto_link:
            reply_buttons += f"""
      <p style="margin: 8px 0 0; font-size: 11px;">
        <a href="{mailto_link}" style="color: #888; text-decoration: underline;">
          or open in your email client to edit first
        </a>
      </p>"""
        reply_buttons += "\n    </div>"
    elif mailto_link:
        reply_buttons = f"""
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
      Ready Concierge &nbsp;Â·&nbsp; Draft Reply Ready
    </p>
  
  
  ğ½‘¥Øø((€€ñ‘¥ØÍÑå±”ô‰‰…­É½Õ¹è€˜å˜İ˜Èì‰½É‘•Èè€ÅÁàÍ½±¥€”ÁáŒì‰½É‘•ÈµÑ½Àè¹½¹”ìÁ…‘‘¥¹œè€ÈÁÁà€ÈÑÁàìˆø(€€€€ñÑ…‰±”ÍÑå±”ô‰İ¥‘Ñ è€ÄÀÀ”ì™½¹ĞµÍ¥é”è€ÄÍÁàì½±½Èè€ŒÔÔÔìˆø(€€€€€€ñÑÈøñÑÍÑå±”ô‰Á…‘‘¥¹œè€ÉÁà€Àìİ¥‘Ñ è€àÁÁàìˆøñÍÑÉ½¹œùÉ½´ğ½ÍÑÉ½¹œøğ½ÑøñÑùí}•ÍŒ¡Õ•ÍÑ}¹…µ”¥ô€™±Ğíí}•ÍŒ¡Õ•ÍÑ}•µ…¥°¥ô™Ğìğ½Ñøğ½ÑÈø(€€€€€€ñÑÈøñÑÍÑå±”ô‰Á…‘‘¥¹œè€ÉÁà€ÀìˆøñÍÑÉ½¹œùMÕ‰©•Ğğ½ÍÑÉ½¹œøğ½ÑøñÑùí}•ÍŒ¡½É¥¥¹…±}ÍÕ‰©•Ğ¥ôğ½Ñøğ½ÑÈø(€€€€€€ñÑÈøñÑÍÑå±”ô‰Á…‘‘¥¹œè€ÉÁà€ÀìˆøñÍÑÉ½¹œùQåÁ”ğ½ÍÑÉ½¹œøğ½ÑøñÑùí}•ÍŒ¡¥¹Ñ•¹Ñ}±…‰•°¥ôğ½Ñøğ½ÑÈø(€€€€ğ½Ñ…‰±”ø(€€(€€(€€ÂöF—cà ¢ÆF—b7G–ÆSÒ&&6¶w&÷VæC¢6fffffc²&÷&FW#¢‚6öÆ–B6SC†63²&÷&FW"×F÷¢æöæS²FF–æs¢#‡‚#Gƒ²föçB×6—¦S¢Wƒ²Æ–æRÖ†V–v‡C¢ãs²#à¢¶G&gEö‡FÖÇĞ¢ÂöF—cà§·&WÇ•ö'WGFöç7Ğ§¶fVVF&6µö&Æö6·Ğ ¢ÆF—b7G–ÆSÒ&&6¶w&÷VæC¢6c–cvc#²&÷&FW#¢‚6öÆ–B6SC†63²&÷&FW"×F÷¢æöæS²FF–æs¢'‚#Gƒ°¢FW‡BÖÆ–vã¢6VçFW#²föçB×6—¦S¢ƒ²6öÆ÷#¢3“““²&÷&FW"×&F—W3¢G‚Gƒ²#à¢÷vW&VB'’&VG’6öæ6–W&vP¢ ¢ ¢ oÙ]‚‚Ø›ÙO‚Ú[‚ˆˆˆ‚‚‚™YˆÙ\ØÊ^ˆİŠHOˆİ‚ˆˆˆ“Z[š[X[S\ØØ\[™Ëˆˆˆ‚ˆYˆ›İ^‚ˆ™]\›ˆˆ‚ˆ™]\›ˆ
ˆİŠ^
Bˆœ™\XÙJ‰ˆ‹‰˜[\ÈŠBˆœ™\XÙJ‹‰›ÈŠBˆœ™\XÙJˆ‹‰™İÈŠBˆœ™\XÙJ	