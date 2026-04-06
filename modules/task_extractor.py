"""
task_extractor.py — Extract committed tasks from AI-generated draft replies.

Uses Claude Haiku to identify concrete action items / commitments made in a
concierge draft, e.g. "Book golf tee time at 10am Friday for 2 guests".
Returns a list of plain-English task strings.
"""

import json
import logging

import anthropic

from config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a task extraction assistant for a luxury hotel concierge team.

Given a draft email reply from a hotel concierge to a guest, extract every specific
commitment or follow-up action item that the hotel has promised to take.

Rules:
- Only extract CONCRETE, ACTIONABLE tasks (e.g. bookings, arrangements, confirmations,
  follow-ups, reservations). Skip vague phrases like "we look forward to your stay".
- Each task should be a short, standalone sentence starting with a verb.
- Return a JSON array of strings. Return [] if there are no commitments.
- Maximum 8 tasks per email.

Examples of good tasks:
  "Book a golf tee time at 10am Friday for 2 guests"
  "Arrange airport transfer for Saturday arrival at 3pm"
  "Reserve a table for 4 at Argyle restaurant on Thursday at 7pm"
  "Send spa menu to guest before arrival"
  "Follow up with golf pro about private lesson availability"

Return ONLY valid JSON — no explanation, no markdown fences.
"""


def extract_tasks(draft_text: str, guest_name: str = "") -> list[str]:
    """
    Extract committed tasks from a concierge draft reply.

    Args:
        draft_text:  The full AI-generated draft reply text.
        guest_name:  Name of the guest (used as context only).

    Returns:
        List of task strings, possibly empty.
    """
    if not draft_text or len(draft_text.strip()) < 50:
        return []

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    context = f"Guest name: {guest_name}\n\n" if guest_name else ""

    try:
        msg = client.messages.create(
            model=settings.haiku_model,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"{context}Draft reply:\n\n{draft_text}",
                }
            ],
        )
        raw = msg.content[0].text.strip()

        # Strip markdown fences if model added them anyway
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        tasks = json.loads(raw)
        if isinstance(tasks, list):
            return [str(t).strip() for t in tasks if t and str(t).strip()]
        return []

    except Exception as exc:
        logger.warning("Task extraction failed (non-fatal): %s", exc)
        return []
