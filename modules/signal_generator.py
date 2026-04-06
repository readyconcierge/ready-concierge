"""
signal_generator.py — Generate the structured signal briefing JSON via Claude Sonnet.

Takes the aggregated signal data + detected patterns and produces a concise,
operationally clear briefing that the hotel team can act on immediately.
"""

import json
import logging
from pathlib import Path

import anthropic

from config import get_settings
from modules.signal_aggregator import AggregatedSignal
from modules.pattern_detector import DetectionResult

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "signal_briefing.txt"

# Expected schema for the signal briefing
_EXPECTED_KEYS = {
    "system_state",
    "what_is_happening",
    "what_matters",
    "suggested_actions",
    "guest_flags",
    "confidence",
}


def _load_system_prompt() -> str:
    """Load the signal briefing system prompt from disk."""
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.error("Signal briefing prompt not found at %s", _PROMPT_PATH)
        raise


def generate_signal_briefing(
    signal: AggregatedSignal,
    detection: DetectionResult,
) -> dict:
    """
    Generate the signal briefing JSON for a property's time window.

    Args:
        signal:    Aggregated email data (intent counts, guest records, etc.).
        detection: Detected patterns and guest flags from pattern_detector.

    Returns:
        A dict with keys: system_state, what_is_happening, what_matters,
        suggested_actions, guest_flags, confidence.

    Raises:
        ValueError: If Claude returns unparseable or structurally invalid JSON.
        anthropic.APIError: Propagated on API failure.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    system_prompt = _load_system_prompt()

    context = _build_context_payload(signal, detection)
    user_message = f"Generate the signal briefing for this data:\n\n{json.dumps(context, indent=2, default=str)}"

    try:
        response = client.messages.create(
            model=settings.sonnet_model,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        briefing = _parse_briefing(raw)
        logger.info(
            "Signal briefing generated for property %d | confidence=%s | patterns=%d",
            signal.property_id,
            briefing.get("confidence", "unknown"),
            len(detection.patterns),
        )
        return briefing

    except anthropic.APIError as exc:
        logger.error("Anthropic API error generating signal briefing: %s", exc)
        raise
    except ValueError as exc:
        logger.error("Signal briefing parse error: %s", exc)
        raise


def _build_context_payload(signal: AggregatedSignal, detection: DetectionResult) -> dict:
    """
    Build the structured context dict passed to Claude for signal generation.
    Keeps the payload concise to stay within token budget.
    """
    pattern_summaries = [
        {
            "type": p.pattern_type,
            "category": p.category,
            "count": p.count,
            "description": p.description,
            "priority": p.priority,
        }
        for p in detection.patterns
    ]

    flag_summaries = [
        {
            "guest_name": f.guest_name,
            "guest_email": f.guest_email,
            "reason": f.reason,
            "priority": f.priority,
        }
        for f in detection.guest_flags
    ]

    # Recent email snippets (most recent 10, subject + first 120 chars of body)
    recent_snippets = [
        {
            "from": e["sender_name"],
            "subject": e["subject"],
            "preview": (e["body"] or "")[:120].replace("\n", " "),
            "intents": e["intents"],
        }
        for e in signal.chronological_emails[-10:]
    ]

    return {
        "hotel_name": signal.hotel_name,
        "time_window": {
            "start": signal.time_window_start.isoformat(),
            "end": signal.time_window_end.isoformat(),
        },
        "total_emails": signal.total_emails,
        "intent_breakdown": signal.intent_counts,
        "multi_intent_guest_count": len(signal.multi_intent_guests),
        "detected_patterns": pattern_summaries,
        "guest_flags": flag_summaries,
        "recent_email_snippets": recent_snippets,
        "has_high_priority_items": detection.has_high_priority,
    }


def _parse_briefing(raw: str) -> dict:
    """Parse and validate the JSON briefing returned by Claude."""
    # Strip markdown fences
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude returned invalid JSON: {exc}\nRaw: {raw[:500]}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")

    # Ensure required keys exist with sensible defaults
    parsed.setdefault("system_state", "No summary available.")
    parsed.setdefault("what_is_happening", [])
    parsed.setdefault("what_matters", [])
    parsed.setdefault("suggested_actions", [])
    parsed.setdefault("guest_flags", [])
    parsed.setdefault("confidence", "low")

    # Normalise confidence
    if parsed["confidence"] not in ("high", "medium", "low"):
        parsed["confidence"] = "low"

    return parsed
