"""
digest_sender.py — Build and send the daily task digest email.

Triggered when anyone emails list@<domain> (e.g. list@aviara.preshift.app).
Returns a list of:
  - Emails responded to today
  - Tasks committed in those responses (with task IDs for easy "done" replies)

Staff can reply with:
  "done 1 3"      → mark tasks #1 and #3 complete
  "done all"      → mark every pending task complete
  "#2 done"       → also valid
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

# Subject prefix used so we can detect replies
DIGEST_SUBJECT_PREFIX = "Ready Concierge task list"


def send_digest(
    recipient_email: str,
    hotel_name: str,
    emails_today: list[dict[str, Any]],
    pending_tasks: list[dict[str, Any]],
    date_label: str,
) -> bool:
    """
    Send the task digest email to the requester.

    Args:
        recipient_email:  Who to send the digest to.
        hotel_name:       Hotel display name.
        emails_today:     List of dicts with keys: subject, sender_name, intents.
        pending_tasks:    List of dicts with keys: id, task_text, guest_name, email_subject.
        date_label:       Human-readable date, e.g. "Wednesday, April 2, 2026".

    Returns:
        True if SendGrid accepted the message.
    """
    settings = get_settings()
    subject = f"{DIGEST_SUBJECT_PREFIX} — {date_label}"

    plain = _build_plain(hotel_name, emails_today, pending_tasks, date_label)
    html = _build_html(hotel_name, emails_today, pending_tasks, date_label)

    payload = {
        "personalizations": [{"to": [{"email": recipient_email}]}],
        "from": {"email": settings.sendgrid_from_email, "name": "Ready Concierge"},
        "reply_to": {"email": settings.sendgrid_from_email, "name": "Ready Concierge"},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain},
            {"type": "text/html", "value": html},
        ],
        "headers": {"X-Ready-Concierge": "task-digest"},
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
        logger.info("Task digest sent to %s (%d tasks)", recipient_email, len(pending_tasks))
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("SendGrid rejected digest: %s — %s", exc.response.status_code, exc.response.text)
        return False
    except httpx.RequestError as exc:
        logger.error("Network error sending digest: %s", exc)
        return False


def parse_done_reply(body: str) -> tuple[bool, list[int]]:
    """
    Parse a "done" reply body to extract which task IDs to mark complete.

    Returns:
        (mark_all, task_ids)
        - mark_all=True means mark every pending task done
        - task_ids is a list of specific IDs (empty if mark_all is True)
    """
    text = body.lower().strip()

    # "done all" or "all done"
    if re.search(r"\ball\b", text) and re.search(r"\bdone\b|completed\b|finished\b", text):
        return True, []

    # Extract numbers: "done 1 2 3", "#1 done", "1, 2, 3 done"
    ids = [int(m) for m in re.findall(r"\b(\d+)\b", text)]
    if ids:
        return False, ids

    # Plain "done" with no numbers → treat as mark all
    if re.search(r"\b(done|completed|finished)\b", text):
        return True, []

    return False, []


# ---------------------------------------------------------------------------
# Email body builders
# ---------------------------------------------------------------------------

def _build_plain(
    hotel_name: str,
    emails_today: list[dict],
    pending_tasks: list[dict],
    date_label: str,
) -> str:
    lines = [
        f"READY CONCIERGE · TASK LIST",
        f"{hotel_name}  ·  {date_label}",
        "=" * 50,
        "",
    ]

    # Emails section
    lines.append(f"EMAILS RESPONDED TO TODAY ({len(emails_today)})")
    lines.append("-" * 40)
    if emails_today:
        for i, e in enumerate(emails_today, 1):
            intents = ", ".join(e.get("intents", [])).title() or "General"
            lines.append(f"  {i}. {e['sender_name']} — \"{e['subject']}\" [{intents}]")
    else:
        lines.append("  No emails processed today.")
    lines.append("")

    # Tasks section
    lines.append(f"PENDING TASKS ({len(pending_tasks)})")
    lines.append("-" * 40)
    if pending_tasks:
        for t in pending_tasks:
            lines.append(f"  ☐  #{t['id']}  {t['task_text']}")
            if t.get("guest_name"):
                lines.append(f"         (re: {t['guest_name']} — {t.get('email_subject', '')})")
    else:
        lines.append("  All clear — no pending tasks.")
    lines.append("")

    # Instructions
    if pending_tasks:
        lines += [
            "─" * 50,
            "MARKING TASKS COMPLETE",
            "",
            "Reply to this email with:",
            "  \"done all\"     → mark every task complete",
            "  \"done 1 3\"     → mark tasks #1 and #3 complete",
            "",
            "Or use the dashboard:",
            "  https://ready-concierge-dashboard.vercel.app/tasks",
            "",
        ]

    lines.append("Powered by Ready Concierge")
    return "\n".join(lines)


def _build_html(
    hotel_name: str,
    emails_today: list[dict],
    pending_tasks: list[dict],
    date_label: str,
) -> str:
    # Build email rows
    email_rows = ""
    if emails_today:
        for i, e in enumerate(emails_today, 1):
            intents = ", ".join(e.get("intents", [])).title() or "General"
            email_rows += f"""
            <tr>
              <td style="padding:6px 8px; color:#888; font-size:12px;">{i}</td>
              <td style="padding:6px 8px; font-weight:500;">{_esc(e['sender_name'])}</td>
              <td style="padding:6px 8px;">{_esc(e['subject'])}</td>
              <td style="padding:6px 8px;"><span style="background:#e8f0fe;color:#1a56db;padding:2px 8px;border-radius:10px;font-size:11px;">{_esc(intents)}</span></td>
            </tr>"""
    else:
        email_rows = '<tr><td colspan="4" style="padding:12px 8px;color:#999;font-style:italic;">No emails processed today.</td></tr>'

    # Build task rows
    task_rows = ""
    if pending_tasks:
        for t in pending_tasks:
            guest_line = ""
            if t.get("guest_name"):
                guest_line = f'<div style="font-size:11px;color:#999;margin-top:2px;">re: {_esc(t["guest_name"])} — {_esc(t.get("email_subject",""))}</div>'
            task_rows += f"""
            <tr>
              <td style="padding:10px 8px; color:#888; font-size:12px; vertical-align:top;">#{t['id']}</td>
              <td style="padding:10px 8px; font-size:22px; vertical-align:top; line-height:1;">☐</td>
              <td style="padding:10px 8px; vertical-align:top;">
                <div style="font-weight:500;">{_esc(t['task_text'])}</div>
                {guest_line}
              </td>
            </tr>"""
    else:
        task_rows = '<tr><td colspan="3" style="padding:12px 8px;color:#999;font-style:italic;">All clear — no pending tasks.</td></tr>'

    instructions_block = ""
    if pending_tasks:
        instructions_block = """
        <div style="background:#f0f7ff;border:1px solid #c3d9f5;border-radius:6px;padding:16px 20px;margin-top:24px;">
          <p style="margin:0 0 8px;font-weight:600;color:#1a56db;font-size:13px;">MARKING TASKS COMPLETE</p>
          <p style="margin:0 0 6px;font-size:13px;color:#333;">
            Reply to this email with:<br>
            &nbsp;&nbsp;<code style="background:#e8f0fe;padding:2px 6px;border-radius:3px;">"done all"</code> — mark every task complete<br>
            &nbsp;&nbsp;<code style="background:#e8f0fe;padding:2px 6px;border-radius:3px;">"done 1 3"</code> — mark tasks #1 and #3 complete
          </p>
          <p style="margin:8px 0 0;font-size:13px;">
            Or use the dashboard:
            <a href="https://ready-concierge-dashboard.vercel.app/tasks" style="color:#1a56db;">
              ready-concierge-dashboard.vercel.app/tasks
            </a>
          </p>
        </div>"""

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Georgia,serif;color:#1a1a1a;max-width:700px;margin:0 auto;padding:24px;">

  <div style="background:#0a1628;color:#c8a96e;padding:16px 24px;border-radius:4px 4px 0 0;">
    <p style="margin:0;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
      Ready Concierge &nbsp;·&nbsp; Task List
    </p>
  </div>

  <div style="background:#f9f7f2;border:1px solid #e0d8cc;border-top:none;padding:14px 24px;">
    <p style="margin:0;font-size:14px;color:#555;">
      <strong>{_esc(hotel_name)}</strong> &nbsp;·&nbsp; {_esc(date_label)}
    </p>
  </div>

  <!-- Emails today -->
  <div style="background:#fff;border:1px solid #e0d8cc;border-top:none;padding:20px 24px;">
    <p style="margin:0 0 12px;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#555;">
      Emails Responded To Today &nbsp;<span style="background:#e8f0fe;color:#1a56db;padding:2px 8px;border-radius:10px;font-size:11px;">{len(emails_today)}</span>
    </p>
    <table style="width:100%;border-collapse:collapse;">
      <thead>
        <tr style="border-bottom:1px solid #eee;">
          <th style="padding:4px 8px;text-align:left;font-size:11px;color:#999;font-weight:400;">#</th>
          <th style="padding:4px 8px;text-align:left;font-size:11px;color:#999;font-weight:400;">From</th>
          <th style="padding:4px 8px;text-align:left;font-size:11px;color:#999;font-weight:400;">Subject</th>
          <th style="padding:4px 8px;text-align:left;font-size:11px;color:#999;font-weight:400;">Type</th>
        </tr>
      </thead>
      <tbody>{email_rows}</tbody>
    </table>
  </div>

  <!-- Pending tasks -->
  <div style="background:#fff;border:1px solid #e0d8cc;border-top:none;padding:20px 24px;">
    <p style="margin:0 0 12px;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#555;">
      Pending Tasks &nbsp;<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:10px;font-size:11px;">{len(pending_tasks)}</span>
    </p>
    <table style="width:100%;border-collapse:collapse;">
      <tbody>{task_rows}</tbody>
    </table>
    {instructions_block}
  </div>

  <div style="background:#f9f7f2;border:1px solid #e0d8cc;border-top:none;padding:12px 24px;
              text-align:center;font-size:11px;color:#999;border-radius:0 0 4px 4px;">
    Powered by Ready Concierge
  </div>

</body>
</html>
"""


def _esc(s: str) -> str:
    """HTML-escape a string."""
    if not s:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
