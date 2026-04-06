"""
guest_memory.py — Guest interaction history for personalized draft replies.

When a guest emails again, the system looks up their prior interactions and
builds a context block that is injected into the draft prompt. This enables
replies that reference past stays, known preferences, and prior requests —
creating the impression of a hotel that truly remembers every guest.

Storage: guest_interactions table (one row per processed email).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import anthropic

from config import get_settings
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def lookup_guest_history(
    db: Session,
    guest_email: str,
    stream_id: Optional[int] = None,
    limit: int = 5,
) -> list[dict]:
    """
    Retrieve the most recent interactions with a guest.

    Args:
        db:          Active SQLAlchemy session.
        guest_email: The guest's email address (case-insensitive lookup).
        stream_id:   Optional stream scope (None = all streams for this guest).
        limit:       Maximum number of interactions to return.

    Returns:
        List of dicts with keys: guest_name, subject, summary, intents,
        feedback, interaction_at.  Most recent first.
    """
    from database import GuestInteraction

    query = (
        db.query(GuestInteraction)
        .filter(GuestInteraction.guest_email == guest_email.lower().strip())
    )
    if stream_id is not None:
        query = query.filter(GuestInteraction.stream_id == stream_id)

    interactions = (
        query
        .order_by(GuestInteraction.interaction_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "guest_name": ix.guest_name,
            "subject": ix.subject,
            "summary": ix.summary,
            "intents": json.loads(ix.intents or "[]"),
            "feedback": ix.feedback,
            "interaction_at": ix.interaction_at.isoformat() if ix.interaction_at else None,
        }
        for ix in interactions
    ]


def record_interaction(
    db: Session,
    stream_id: int,
    guest_email: str,
    guest_name: str,
    subject: str,
    intents: list[str],
    draft_text: Optional[str] = None,
    body: Optional[str] = None,
) -> None:
    """
    Record a guest interaction for future memory lookups.

    Generates a one-line summary of the interaction using Claude Haiku
    (fast, cheap) so future lookups have concise context.

    Args:
        db:          Active SQLAlchemy session.
        stream_id:   The stream this interaction belongs to.
        guest_email: Guest email address.
        guest_name:  Guest display name.
        subject:     Email subject line.
        intents:     Classified intent labels.
        draft_text:  The draft reply that was generated (optional).
        body:        The original email body (for summary generation).
    """
    from database import GuestInteraction

    # Generate a one-line summary for future context
    summary = _generate_summary(guest_name, subject, body, intents)

    interaction = GuestInteraction(
        stream_id=stream_id,
        guest_email=guest_email.lower().strip(),
        guest_name=guest_name,
        subject=subject,
        summary=summary,
        intents=json.dumps(intents),
        draft_text=draft_text,
        interaction_at=datetime.now(timezone.utc),
    )
    db.add(interaction)
    # Don't commit here — let the caller manage the transaction

    logger.info(
        "Recorded guest interaction | guest=%s | subject=%r | summary=%r",
        guest_email, subject, summary,
    )


def build_guest_context(history: list[dict]) -> str:
    """
    Format guest history into a context block for the draft prompt.

    Returns an empty string if no history exists.

    Example output:
        === GUEST HISTORY ===
        This is a returning guest. Previous interactions:
        - Mar 15, 2026: Requested anniversary dinner at Argyle; arranged ocean-view table for two. (Dining, Celebration)
        - Jan 8, 2026: Asked about airport transfer for early-morning departure; car service confirmed. (Transportation, Departure)
        =====================
    """
    if not history:
        return ""

    lines = [
        "=== GUEST HISTORY ===",
        "This is a returning guest. Previous interactions:",
    ]

    for ix in history:
        date_str = "Unknown date"
        if ix.get("interaction_at"):
            try:
                dt = datetime.fromisoformat(ix["interaction_at"])
                date_str = dt.strftime("%b %-d, %Y")
            except (ValueError, TypeError):
                pass

        intent_str = ", ".join(
            i.replace("_", " ").title()
            for i in ix.get("intents", [])
        )
        summary = ix.get("summary") or ix.get("subject") or "No details recorded"
        feedback_note = ""
        if ix.get("feedback") == "perfect":
            feedback_note = " [Staff confirmed: draft was used as-is]"

        lines.append(f"- {date_str}: {summary} ({intent_str}){feedback_note}")

    lines.append("=====================")
    return "\n".join(lines)


def _generate_summary(
    guest_name: str,
    subject: str,
    body: Optional[str],
    intents: list[str],
) -> str:
    """
    Generate a one-line summary of this interaction for future memory.

    Uses Claude Haiku for speed and cost. Falls back to the subject line
    if the API call fails.
    """
    if not body:
        return subject or "No details available"

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.create(
            model=settings.haiku_model,
            max_tokens=100,
            system=(
                "Summarize this hotel guest email in ONE sentence (max 25 words). "
                "Focus on what they requested and any personal details revealed "
                "(occasion, preferences, party size, dates). "
                "Write in past tense. No quotes, no preamble."
            ),
            messages=[{
                "role": "user",
                "content": f"Guest: {guest_name}\nSubject: {subject}\n\n{body[:500]}",
            }],
        )
        summary = response.content[0].text.strip()
        # Ensure it's truly one line
        summary = summary.split("\n")[0].strip()
        return summary

    except Exception as exc:
        logger.warning("Guest summary generation failed (non-fatal): %s", exc)
        return subject or "No details available"
