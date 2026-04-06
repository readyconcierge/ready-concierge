"""
intent_classifier.py — Classify a guest email into one or more intents.

Uses Claude (Haiku for speed/cost) to return a JSON array of intents from
a fixed taxonomy. Falls back to ["general_inquiry"] on any error.
"""

import json
import logging
from typing import Any

import anthropic

from config import get_settings

logger = logging.getLogger(__name__)

VALID_INTENTS = {
    "dining",
    "transportation",
    "arrival",
    "departure",
    "celebration",
    "spa",
    "golf",
    "complaint",
    "vip_request",
    "general_inquiry",
}

_SYSTEM_PROMPT = """\
You are a hotel concierge request classifier. Your job is to read a guest email \
and return a JSON array of intent labels that describe what the guest is asking for.

Only use intents from this exact list:
- dining         (restaurant reservations, room service, dietary needs, F&B requests)
- transportation (car service, airport transfers, valet, local directions)
- arrival        (early check-in, welcome amenities, room preferences, ETA)
- departure      (late checkout, luggage storage, airport drop-off)
- celebration    (anniversaries, birthdays, honeymoons, special occasions)
- spa            (treatments, bookings, wellness, fitness)
- golf           (tee times, equipment, lessons, courses)
- complaint      (dissatisfaction, problems, issues, negative sentiment)
- vip_request    (special access, upgrades, exclusive experiences, high-value guest)
- general_inquiry (anything that doesn't fit above)

Rules:
- Return ONLY a valid JSON array of strings, e.g. ["dining", "celebration"]
- Include ALL that apply — most emails have 1-2 intents
- Always include at least one intent
- Do NOT include any explanation or text outside the JSON array
"""


def classify_intent(subject: str, body: str) -> list[str]:
    """
    Classify the intent(s) of a guest email.

    Args:
        subject: Email subject line.
        body:    Plain-text email body.

    Returns:
        A list of intent strings (subset of VALID_INTENTS).
        Falls back to ["general_inquiry"] on any error.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    user_message = f"Subject: {subject}\n\n{body}"

    try:
        response = client.messages.create(
            model=settings.haiku_model,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        intents = _parse_intents(raw)
        logger.info("Classified intents: %s", intents)
        return intents

    except anthropic.APIError as exc:
        logger.error("Anthropic API error during intent classification: %s", exc)
        return ["general_inquiry"]
    except Exception as exc:
        logger.error("Unexpected error during intent classification: %s", exc)
        return ["general_inquiry"]


def _parse_intents(raw: str) -> list[str]:
    """Parse and validate the JSON array returned by Claude."""
    # Strip any markdown fences in case the model wrapped with ```json
    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Intent classifier returned non-JSON: %r", raw)
        return ["general_inquiry"]

    if not isinstance(parsed, list):
        logger.warning("Intent classifier returned non-list: %r", parsed)
        return ["general_inquiry"]

    # Filter to valid intents only
    valid = [i for i in parsed if isinstance(i, str) and i in VALID_INTENTS]
    if not valid:
        logger.warning("No valid intents found in %r, defaulting to general_inquiry", parsed)
        return ["general_inquiry"]

    return valid
