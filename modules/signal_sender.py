"""
signal_sender.py — Format the signal briefing JSON and send it via SendGrid.

Produces both a plain-text and HTML version of the signal email.
Subject: "Today's Concierge Signal – [Hotel Name]"
"""

import logging
from datetime import datetime, timezone

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def send_signal_email(
    recipient_emails: list[str],
    hotel_name: str,
    briefing: dict,
    time_window_start: datetime,
    time_window_end: datetime,
) -> bool:
    """
    Send the formatted signal briefing to all recipient emails.

    Args:
        recipient_emails:  List of staff/manager email addresses.
        hotel_name:        Hotel display name.
        briefing:          Structured JSON briefing from signal_generator.
        time_window_start: Start of the signal's time window.
        time_window_end:   End of the signal's time window.

    Returns:
        True if Mailgun accepted the send, False otherwise.
    """
    if not recipient_emails:
        logger.warning("No recipients configured for signal email — skipping.")
        return False

    settings = get_settings()
    window_str = _format_window(time_window_start, time_window_end)
    subject = f"Today's Concierge Signal \u2013 {hotel_name}"

    plain = _build_plain(briefing, hotel_name, window_str)
    html = _build_html(briefing, hotel_name, window_str)

    payload = {
        "personalizations": [
            {"to": [{"email": addr} for addr in recipient_emails]}
        ],
        "from": {"email": settings.sendgrid_from_email, "name": "Ready Concierge"},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain},
            {"type": "text/html", "value": html},
        ],
        "headers": {"X-Ready-Concierge": "signal-briefing"},
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
            "Signal email sent to %d recipients for %r via SendGrid",
            len(recipient_emails),
            hotel_name,
        )
        return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "SendGrid rejected signal send: %s — %s",
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except httpx.RequestError as exc:
        logger.error("Network error sending signal email: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_window(start: datetime, end: datetime) -> str:
    fmt = "%b %d, %Y %I:%M %p UTC"
    start_s = start.strftime(fmt) if start else "?"
    end_s = end.strftime(fmt) if end else "?"
    return f"{start_s} – {end_s}"


def _bullets(items: list, prefix: str = "• ") -> str:
    if not items:
        return f"{prefix}Nothing to report."
    return "\n".join(f"{prefix}{item}" for item in items)


def _build_plain(briefing: dict, hotel_name: str, window: str) -> str:
    flags = briefing.get("guest_flags", [])
    flag_lines = (
        _bullets([f"{f.get('name', f.get('guest_name', '?'))} – {f.get('reason', '?')}" for f in flags])
        if flags
        else "• None."
    )
    confidence = briefing.get("confidence", "low").title()

    return f"""\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TODAY'S CONCIERGE SIGNAL  ·  {hotel_name.upper()}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYSTEM STATE
{briefing.get("system_state", "—")}

WHAT'S HAPPENING
{_bullets(briefing.get("what_is_happening", []))}

WHAT MATTERS RIGHT NOW
{_bullets(briefing.get("what_matters", []))}

SUGGESTED ACTIONS
{_bullets(briefing.get("suggested_actions", []))}

GUEST FLAGS
{flag_lines}

Confidence: {confidence}
---
Ready Concierge · {hotel_name} · {window}
"""


def _build_html(briefing: dict, hotel_name: str, window: str) -> str:
    confidence = briefing.get("confidence", "low").lower()
    confidence_color = {"high": "#2d6a2d", "medium": "#7a5c00", "low": "#8b1a1a"}.get(confidence, "#555")
    confidence_label = confidence.title()

    def html_bullets(items: list) -> str:
        if not items:
            return "<li style='color:#888'>Nothing to report.</li>"
        return "".join(f"<li>{_esc(str(item))}</li>" for item in items)

    flags = briefing.get("guest_flags", [])
    flag_html = (
        "".join(
            f"<li><strong>{_esc(f.get('name', f.get('guest_name', '?')))}</strong> "
            f"– {_esc(f.get('reason', '?'))}</li>"
            for f in flags
        )
        if flags
        else "<li style='color:#888'>None flagged.</li>"
    )

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Georgia, serif; color: #1a1a1a; max-width: 680px; margin: 0 auto; padding: 24px;">

  <!-- Header -->
  <div style="background: #0a1628; padding: 20px 28px; border-radius: 4px 4px 0 0;">
    <p style="margin: 0; font-size: 10px; letter-spacing: 3px; color: #c8a96e; text-transform: uppercase;">
      Ready Concierge
    </p>
    <h1 style="margin: 6px 0 0; font-size: 20px; color: #ffffff; font-weight: normal;">
      Today's Concierge Signal
    </h1>
    <p style="margin: 4px 0 0; font-size: 13px; color: #8a9bb5;">{_esc(hotel_name)}</p>
  </div>

  <!-- System State -->
  <div style="background: #f4f1eb; border-left: 4px solid #c8a96e; padding: 16px 24px; margin-top: 0;
              border-right: 1px solid #e0d8cc; border-bottom: 1px solid #e0d8cc;">
    <p style="margin: 0; font-size: 11px; letter-spacing: 2px; color: #999; text-transform: uppercase;">System State</p>
    <p style="margin: 8px 0 0; font-size: 16px; font-style: italic; color: #1a1a1a;">
      {_esc(briefing.get("system_state", "—"))}
    </p>
  </div>

  <!-- Body sections -->
  <div style="background: #ffffff; border: 1px solid #e0d8cc; border-top: none; padding: 24px 28px;">

    {_section_html("What's Happening", html_bullets(briefing.get("what_is_happening", [])))}
    {_section_html("What Matters Right Now", html_bullets(briefing.get("what_matters", [])))}
    {_section_html("Suggested Actions", html_bullets(briefing.get("suggested_actions", [])))}

    <h3 style="font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #c0392b; margin: 28px 0 8px;">
      Guest Flags
    </h3>
    <ul style="margin: 0; padding-left: 20px; line-height: 1.8;">{flag_html}</ul>

  </div>

  <!-- Footer -->
  <div style="background: #f9f7f2; border: 1px solid #e0d8cc; border-top: none; padding: 14px 28px;
              border-radius: 0 0 4px 4px; display: flex; justify-content: space-between; align-items: center;">
    <span style="font-size: 12px; color: #888;">{_esc(window)}</span>
    <span style="font-size: 12px; font-weight: bold; color: {confidence_color};">
      Confidence: {confidence_label}
    </span>
  </div>
  <p style="text-align: center; font-size: 11px; color: #bbb; margin-top: 16px;">
    Powered by Ready Concierge &nbsp;·&nbsp; {_esc(hotel_name)}
  </p>

</body>
</html>
"""


def _section_html(title: str, bullets_html: str) -> str:
    return f"""\
<h3 style="font-size: 11px; letter-spacing: 2px; text-transform: uppercase; color: #0a1628; margin: 28px 0 8px;">
  {_esc(title)}
</h3>
<ul style="margin: 0; padding-left: 20px; line-height: 1.8;">{bullets_html}</ul>
"""


def _esc(text: str) -> str:
    """Minimal HTML escaping."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
