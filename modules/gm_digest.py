"""
gm_digest.py — Weekly GM intelligence digest.

Every Monday at 7:00 AM, the GM (and all signal recipients) receive a
high-level weekly report covering:
  - Email volume and intent breakdown
  - Draft feedback stats (acceptance rate)
  - Top returning guests
  - Task completion rate
  - AI-generated executive insights

This is the "tell your boss about it" feature. When a GM sees their team
handling 47 guest emails with 91% AI-draft acceptance — that's the number
that makes Ready Concierge non-negotiable.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
import httpx

from config import get_settings

logger = logging.getLogger(__name__)

_SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def generate_weekly_digest(
    stream_id: int,
    days_back: int = 7,
) -> dict[str, Any] | None:
    """
    Build the weekly digest data for a stream.

    Returns a dict with all the stats and insights, or None if no data.
    """
    from database import (
        CommittedTask, DraftFeedback, DraftReply, Email,
        GuestInteraction, Stream, SessionLocal,
    )

    db = SessionLocal()
    try:
        stream = db.query(Stream).filter(Stream.id == stream_id).first()
        if not stream:
            logger.error("GM digest: stream %d not found", stream_id)
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        # --- Email volume ---
        emails = (
            db.query(Email)
            .filter(Email.stream_id == stream_id, Email.received_at >= cutoff)
            .all()
        )
        if not emails:
            logger.info("GM digest: no emails in last %d days for stream %d", days_back, stream_id)
            return None

        total_emails = len(emails)

        # Intent breakdown
        intent_counts: dict[str, int] = {}
        for e in emails:
            for intent in json.loads(e.intent or "[]"):
                intent_counts[intent] = intent_counts.get(intent, 0) + 1

        # Sort by count descending
        intent_breakdown = sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)

        # --- Draft feedback stats ---
        drafts = (
            db.query(DraftReply)
            .join(Email, DraftReply.email_id == Email.id)
            .filter(Email.stream_id == stream_id, Email.received_at >= cutoff)
            .all()
        )
        total_drafts = len(drafts)
        drafts_sent = sum(1 for d in drafts if d.sent_at)
        drafts_reviewed = sum(1 for d in drafts if d.accepted is not None)
        drafts_accepted = sum(1 for d in drafts if d.accepted is True)
        acceptance_rate = (
            round(drafts_accepted / drafts_reviewed * 100) if drafts_reviewed > 0 else None
        )

        # Average reply time
        processing_times = [d.processing_ms for d in drafts if d.processing_ms is not None]
        avg_reply_ms = round(sum(processing_times) / len(processing_times)) if processing_times else None
        avg_reply_seconds = round(avg_reply_ms / 1000, 1) if avg_reply_ms else None

        # --- Feedback clicks ---
        feedback_records = (
            db.query(DraftFeedback)
            .filter(
                DraftFeedback.stream_id == stream_id,
                DraftFeedback.clicked_at >= cutoff,
            )
            .all()
        )
        feedback_perfect = sum(1 for f in feedback_records if f.verdict == "perfect")
        feedback_changed = sum(1 for f in feedback_records if f.verdict == "changed")

        # --- Task stats ---
        tasks_created = (
            db.query(CommittedTask)
            .filter(
                CommittedTask.stream_id == stream_id,
                CommittedTask.created_at >= cutoff,
            )
            .all()
        )
        total_tasks = len(tasks_created)
        tasks_completed = sum(1 for t in tasks_created if t.completed)
        tasks_pending = total_tasks - tasks_completed
        completion_rate = (
            round(tasks_completed / total_tasks * 100) if total_tasks > 0 else None
        )

        # --- Top guests (most interactions) ---
        interactions = (
            db.query(GuestInteraction)
            .filter(
                GuestInteraction.stream_id == stream_id,
                GuestInteraction.interaction_at >= cutoff,
            )
            .all()
        )
        guest_counts: dict[str, dict] = {}
        for ix in interactions:
            key = ix.guest_email.lower()
            if key not in guest_counts:
                guest_counts[key] = {"name": ix.guest_name, "email": ix.guest_email, "count": 0}
            guest_counts[key]["count"] += 1

        top_guests = sorted(guest_counts.values(), key=lambda x: x["count"], reverse=True)[:5]

        # --- AI-generated executive insights ---
        insights = _generate_insights(
            hotel_name=stream.display_name,
            total_emails=total_emails,
            intent_breakdown=intent_breakdown,
            acceptance_rate=acceptance_rate,
            total_drafts=total_drafts,
            drafts_sent=drafts_sent,
            feedback_perfect=feedback_perfect,
            feedback_changed=feedback_changed,
            total_tasks=total_tasks,
            tasks_completed=tasks_completed,
            top_guests=top_guests,
            days_back=days_back,
        )

        return {
            "stream_id": stream_id,
            "hotel_name": stream.display_name,
            "period_start": cutoff.isoformat(),
            "period_end": datetime.now(timezone.utc).isoformat(),
            "days_back": days_back,
            "total_emails": total_emails,
            "intent_breakdown": intent_breakdown,
            "total_drafts": total_drafts,
            "drafts_sent": drafts_sent,
            "drafts_reviewed": drafts_reviewed,
            "drafts_accepted": drafts_accepted,
            "acceptance_rate": acceptance_rate,
            "feedback_perfect": feedback_perfect,
            "feedback_changed": feedback_changed,
            "total_tasks": total_tasks,
            "tasks_completed": tasks_completed,
            "tasks_pending": tasks_pending,
            "completion_rate": completion_rate,
            "top_guests": top_guests,
            "avg_reply_seconds": avg_reply_seconds,
            "insights": insights,
        }

    except Exception as exc:
        logger.error("GM digest generation error for stream %d: %s", stream_id, exc, exc_info=True)
        return None
    finally:
        db.close()


def send_gm_digest(
    recipient_emails: list[str],
    digest: dict[str, Any],
) -> bool:
    """
    Send the weekly GM digest to a list of recipients.

    Returns True if SendGrid accepted the message.
    """
    settings = get_settings()

    period_end = datetime.fromisoformat(digest["period_end"])
    date_label = period_end.strftime("%B %-d, %Y")
    subject = f"Weekly Intelligence Brief — {digest['hotel_name']} — {date_label}"

    plain = _build_plain(digest)
    html = _build_html(digest)

    payload = {
        "personalizations": [{"to": [{"email": e} for e in recipient_emails]}],
        "from": {"email": settings.sendgrid_from_email, "name": "Ready Concierge"},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain},
            {"type": "text/html", "value": html},
        ],
        "headers": {"X-Ready-Concierge": "gm-weekly-digest"},
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
            "GM weekly digest sent to %d recipients | emails=%d | acceptance=%s%%",
            len(recipient_emails),
            digest["total_emails"],
            digest.get("acceptance_rate", "N/A"),
        )
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("SendGrid rejected GM digest: %s — %s", exc.response.status_code, exc.response.text)
        return False
    except httpx.RequestError as exc:
        logger.error("Network error sending GM digest: %s", exc)
        return False


def _generate_insights(
    hotel_name: str,
    total_emails: int,
    intent_breakdown: list[tuple[str, int]],
    acceptance_rate: int | None,
    total_drafts: int,
    drafts_sent: int,
    feedback_perfect: int,
    feedback_changed: int,
    total_tasks: int,
    tasks_completed: int,
    top_guests: list[dict],
    days_back: int,
) -> str:
    """Generate executive insights using Claude Haiku."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    intent_str = ", ".join(f"{i}: {c}" for i, c in intent_breakdown) if intent_breakdown else "none"
    top_guest_str = ", ".join(
        f"{g['name']} ({g['count']} interactions)" for g in top_guests
    ) if top_guests else "none"

    try:
        response = client.messages.create(
            model=settings.haiku_model,
            max_tokens=400,
            system=(
                "You are an executive intelligence briefer for a luxury hotel. "
                "Write 3-4 concise bullet points (each 1-2 sentences) that a GM would find "
                "actionable. Focus on: trends worth noting, operational wins, areas to watch, "
                "and any guest-experience patterns. Be specific, not generic. No preamble."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Hotel: {hotel_name}\n"
                    f"Period: last {days_back} days\n"
                    f"Total guest emails: {total_emails}\n"
                    f"Intent breakdown: {intent_str}\n"
                    f"AI drafts generated: {total_drafts}, sent: {drafts_sent}\n"
                    f"Staff feedback: {feedback_perfect} perfect, {feedback_changed} needed changes "
                    f"(acceptance rate: {acceptance_rate}%)\n" if acceptance_rate else ""
                    f"Tasks created: {total_tasks}, completed: {tasks_completed}\n"
                    f"Top guests: {top_guest_str}\n"
                ),
            }],
        )
        return response.content[0].text.strip()

    except Exception as exc:
        logger.warning("GM insights generation failed (non-fatal): %s", exc)
        return "AI insights unavailable this week."


# ---------------------------------------------------------------------------
# Email body builders
# ---------------------------------------------------------------------------

def _build_plain(digest: dict) -> str:
    lines = [
        "━" * 50,
        "READY CONCIERGE · WEEKLY INTELLIGENCE BRIEF",
        "━" * 50,
        f"{digest['hotel_name']}",
        f"Week ending {datetime.fromisoformat(digest['period_end']).strftime('%B %-d, %Y')}",
        "",
        "KEY METRICS",
        "─" * 40,
        f"  Guest emails handled:    {digest['total_emails']}",
        f"  AI drafts generated:     {digest['total_drafts']}",
        f"  Drafts sent to staff:    {digest['drafts_sent']}",
    ]

    if digest.get("acceptance_rate") is not None:
        lines.append(f"  Draft acceptance rate:    {digest['acceptance_rate']}%")
    if digest.get("avg_reply_seconds") is not None:
        lines.append(f"  Avg reply time:          {digest['avg_reply_seconds']}s")

    lines += [
        f"  Tasks created:           {digest['total_tasks']}",
        f"  Tasks completed:         {digest['tasks_completed']}",
        f"  Tasks pending:           {digest['tasks_pending']}",
    ]

    if digest.get("completion_rate") is not None:
        lines.append(f"  Task completion rate:     {digest['completion_rate']}%")

    lines += ["", "REQUEST TYPES", "─" * 40]
    for intent, count in digest.get("intent_breakdown", []):
        label = intent.replace("_", " ").title()
        lines.append(f"  {label}: {count}")

    if digest.get("top_guests"):
        lines += ["", "TOP GUESTS", "─" * 40]
        for g in digest["top_guests"]:
            lines.append(f"  {g['name']} ({g['email']}) — {g['count']} interactions")

    if digest.get("insights"):
        lines += ["", "EXECUTIVE INSIGHTS", "─" * 40, digest["insights"]]

    lines += ["", "━" * 50, "Powered by Ready Concierge"]
    return "\n".join(lines)


def _build_html(digest: dict) -> str:
    period_end = datetime.fromisoformat(digest["period_end"]).strftime("%B %-d, %Y")

    # Metrics cards
    acceptance_display = f"{digest['acceptance_rate']}%" if digest.get("acceptance_rate") is not None else "—"
    completion_display = f"{digest['completion_rate']}%" if digest.get("completion_rate") is not None else "—"
    reply_time_display = f"{digest['avg_reply_seconds']}s" if digest.get("avg_reply_seconds") is not None else "—"

    # Intent breakdown rows
    intent_rows = ""
    for intent, count in digest.get("intent_breakdown", [])[:8]:
        label = intent.replace("_", " ").title()
        pct = round(count / digest["total_emails"] * 100) if digest["total_emails"] else 0
        bar_width = max(4, min(pct * 2, 200))
        intent_rows += f"""
        <tr>
          <td style="padding:6px 12px;font-size:13px;color:#333;">{_esc(label)}</td>
          <td style="padding:6px 12px;font-size:13px;color:#666;">{count}</td>
          <td style="padding:6px 12px;">
            <div style="background:#e8f0fe;border-radius:3px;height:14px;width:{bar_width}px;"></div>
          </td>
          <td style="padding:6px 12px;font-size:12px;color:#999;">{pct}%</td>
        </tr>"""

    # Top guests rows
    guest_rows = ""
    for g in digest.get("top_guests", []):
        guest_rows += f"""
        <tr>
          <td style="padding:6px 12px;font-size:13px;font-weight:500;">{_esc(g['name'])}</td>
          <td style="padding:6px 12px;font-size:12px;color:#888;">{_esc(g['email'])}</td>
          <td style="padding:6px 12px;font-size:13px;color:#0a1628;font-weight:600;">{g['count']}</td>
        </tr>"""

    # Insights
    insights_html = ""
    if digest.get("insights"):
        raw = digest["insights"]
        # Convert bullet points to HTML
        insight_lines = raw.replace("• ", "").replace("- ", "").split("\n")
        insight_items = "".join(
            f"<li style='margin-bottom:8px;line-height:1.5;'>{_esc(line.strip())}</li>"
            for line in insight_lines if line.strip()
        )
        insights_html = f"""
    <div style="background:#fff;border:1px solid #e0d8cc;border-top:none;padding:20px 24px;">
      <p style="margin:0 0 12px;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#c8a96e;">
        Executive Insights
      </p>
      <ul style="margin:0;padding-left:20px;font-size:14px;color:#333;">
        {insight_items}
      </ul>
    </div>"""

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Georgia,serif;color:#1a1a1a;max-width:700px;margin:0 auto;padding:24px;">

  <!-- Header -->
  <div style="background:#0a1628;color:#c8a96e;padding:20px 24px;border-radius:4px 4px 0 0;">
    <p style="margin:0 0 4px;font-size:11px;letter-spacing:2px;text-transform:uppercase;">
      Ready Concierge &nbsp;·&nbsp; Weekly Intelligence Brief
    </p>
    <p style="margin:0;font-size:16px;color:#ffffff;font-weight:400;">
      {_esc(digest['hotel_name'])} &nbsp;·&nbsp; Week ending {_esc(period_end)}
    </p>
  </div>

  <!-- Key Metrics -->
  <div style="background:#f9f7f2;border:1px solid #e0d8cc;border-top:none;padding:20px 24px;">
    <table style="width:100%;text-align:center;">
      <tr>
        <td style="padding:12px;">
          <div style="font-size:28px;font-weight:700;color:#0a1628;">{digest['total_emails']}</div>
          <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;">Guest Emails</div>
        </td>
        <td style="padding:12px;">
          <div style="font-size:28px;font-weight:700;color:#0a1628;">{acceptance_display}</div>
          <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;">Draft Acceptance</div>
        </td>
        <td style="padding:12px;">
          <div style="font-size:28px;font-weight:700;color:#0a1628;">{digest['tasks_completed']}/{digest['total_tasks']}</div>
          <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;">Tasks Completed</div>
        </td>
        <td style="padding:12px;">
          <div style="font-size:28px;font-weight:700;color:#0a1628;">{completion_display}</div>
          <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;">Completion Rate</div>
        </td>
        <td style="padding:12px;">
          <div style="font-size:28px;font-weight:700;color:#0a1628;">{reply_time_display}</div>
          <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;">Avg Reply Time</div>
        </td>
      </tr>
    </table>
  </div>

  <!-- Request Types -->
  <div style="background:#fff;border:1px solid #e0d8cc;border-top:none;padding:20px 24px;">
    <p style="margin:0 0 12px;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#c8a96e;">
      Request Types This Week
    </p>
    <table style="width:100%;border-collapse:collapse;">
      {intent_rows}
    </table>
  </div>

  <!-- AI Feedback -->
  <div style="background:#fff;border:1px solid #e0d8cc;border-top:none;padding:20px 24px;">
    <p style="margin:0 0 12px;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#c8a96e;">
      AI Draft Performance
    </p>
    <table style="width:100%;text-align:center;">
      <tr>
        <td style="padding:8px;">
          <div style="font-size:22px;font-weight:700;color:#2d6a2d;">{digest['feedback_perfect']}</div>
          <div style="font-size:11px;color:#888;">Perfect (used as-is)</div>
        </td>
        <td style="padding:8px;">
          <div style="font-size:22px;font-weight:700;color:#c27803;">{digest['feedback_changed']}</div>
          <div style="font-size:11px;color:#888;">Needed Changes</div>
        </td>
        <td style="padding:8px;">
          <div style="font-size:22px;font-weight:700;color:#0a1628;">{digest['drafts_sent']}</div>
          <div style="font-size:11px;color:#888;">Total Sent</div>
        </td>
      </tr>
    </table>
  </div>

  <!-- Top Guests -->
  {"" if not guest_rows else f'''
  <div style="background:#fff;border:1px solid #e0d8cc;border-top:none;padding:20px 24px;">
    <p style="margin:0 0 12px;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#c8a96e;">
      Top Guests This Week
    </p>
    <table style="width:100%;border-collapse:collapse;">
      <thead>
        <tr style="border-bottom:1px solid #eee;">
          <th style="padding:4px 12px;text-align:left;font-size:10px;color:#999;font-weight:400;">Guest</th>
          <th style="padding:4px 12px;text-align:left;font-size:10px;color:#999;font-weight:400;">Email</th>
          <th style="padding:4px 12px;text-align:left;font-size:10px;color:#999;font-weight:400;">Interactions</th>
        </tr>
      </thead>
      <tbody>{guest_rows}</tbody>
    </table>
  </div>'''}

  <!-- Insights -->
  {insights_html}

  <!-- Footer -->
  <div style="background:#f9f7f2;border:1px solid #e0d8cc;border-top:none;padding:16px 24px;
              text-align:center;font-size:11px;color:#999;border-radius:0 0 4px 4px;">
    Powered by Ready Concierge &nbsp;·&nbsp;
    <a href="https://ready-concierge-dashboard.vercel.app" style="color:#c8a96e;text-decoration:none;">
      View Dashboard
    </a>
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
