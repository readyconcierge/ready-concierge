"""
guardrails.py — Safety and quality checks for AI-generated draft replies.

Three guardrail layers:
  1. Intent filter    — rule-based; flags complaint / high-stakes intents for human review
  2. Topic filter     — regex-based; catches medical, legal, security, media keywords
  3. Confidence check — LLM-based; detects hallucination risk (ungrounded specific claims)

All three layers return a GuardrailResult that controls whether the draft is
auto-sent or held in the human review queue.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Confidence levels
# ---------------------------------------------------------------------------
CONFIDENCE_HIGH   = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW    = "low"

# ---------------------------------------------------------------------------
# Layer 1a — Intents that always require a human to review before sending
# ---------------------------------------------------------------------------
REVIEW_REQUIRED_INTENTS = {"complaint"}

# ---------------------------------------------------------------------------
# Layer 1b — Keyword patterns that signal high-risk or out-of-scope content.
# Tuple: (compiled_pattern, short_flag_name)
# ---------------------------------------------------------------------------
SENSITIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\b(attorney|lawyer|lawsuit|legal action|sue\b|suing|litigation|my lawyer)\b",
            re.I,
        ),
        "legal_threat",
    ),
    (
        re.compile(
            r"\b(ambulance|911|emergency room|\bER\b|hospital|badly injured|unconscious|"
            r"medical emergency|allergic reaction|can't breathe)\b",
            re.I,
        ),
        "medical_emergency",
    ),
    (
        re.compile(
            r"\b(stolen|theft|robbery|assault|harassed|police report|crime|security incident|"
            r"missing belongings)\b",
            re.I,
        ),
        "security_incident",
    ),
    (
        re.compile(
            r"\b(journalist|reporter|press release|news story|media inquiry|on the record|"
            r"publishing a story|writing an article)\b",
            re.I,
        ),
        "media_inquiry",
    ),
    (
        re.compile(
            r"\b(TripAdvisor|Yelp|Google review|social media|going public|tweet about|"
            r"post about this|warn others|BBB complaint)\b",
            re.I,
        ),
        "public_escalation",
    ),
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GuardrailResult:
    """Outcome of running all guardrail layers against a draft."""
    safe_to_send: bool              # True → auto-send OK; False → hold for human review
    confidence: str                  # high | medium | low
    flags: list[str] = field(default_factory=list)
    review_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def evaluate_draft(
    draft: str,
    subject: str,
    body: str,
    intents: list[str],
    hotel_name: str,
    knowledge_context: Optional[str] = None,
) -> GuardrailResult:
    """
    Run all three guardrail layers against a generated draft.

    Args:
        draft:             The AI-generated draft reply text.
        subject:           Original email subject.
        body:              Original email body (plain text).
        intents:           Intent labels from the intent classifier.
        hotel_name:        Hotel/company name (for context in LLM check).
        knowledge_context: RAG context that was injected into the draft prompt, if any.

    Returns:
        GuardrailResult — whether the draft is safe to auto-send or needs review.
    """
    flags: list[str] = []

    # ── Layer 1a: Intent-based review trigger ──────────────────────────────
    triggered_intents = [i for i in intents if i in REVIEW_REQUIRED_INTENTS]
    if triggered_intents:
        reason = f"Requires human review — sensitive intent: {', '.join(triggered_intents)}"
        logger.info("Guardrail L1a triggered | intents=%s", triggered_intents)
        return GuardrailResult(
            safe_to_send=False,
            confidence=CONFIDENCE_MEDIUM,
            flags=[f"intent:{i}" for i in triggered_intents],
            review_reason=reason,
        )

    # ── Layer 1b: Keyword / topic filter ──────────────────────────────────
    combined_text = f"{subject} {body}"
    for pattern, flag_name in SENSITIVE_PATTERNS:
        if pattern.search(combined_text):
            flags.append(f"topic:{flag_name}")

    if flags:
        readable = ", ".join(f.split(":", 1)[1] for f in flags)
        reason = f"Sensitive topic detected — requires human review: {readable}"
        logger.info("Guardrail L1b triggered | flags=%s", flags)
        return GuardrailResult(
            safe_to_send=False,
            confidence=CONFIDENCE_LOW,
            flags=flags,
            review_reason=reason,
        )

    # ── Layer 2: LLM confidence / grounding check ─────────────────────────
    confidence, conf_flags, conf_reason = _check_confidence(
        draft=draft,
        subject=subject,
        body=body,
        hotel_name=hotel_name,
        knowledge_context=knowledge_context,
    )
    flags.extend(conf_flags)

    safe = confidence != CONFIDENCE_LOW
    review_reason = conf_reason if not safe else None

    return GuardrailResult(
        safe_to_send=safe,
        confidence=confidence,
        flags=flags,
        review_reason=review_reason,
    )


# ---------------------------------------------------------------------------
# Layer 2 implementation
# ---------------------------------------------------------------------------

def _check_confidence(
    draft: str,
    subject: str,
    body: str,
    hotel_name: str,
    knowledge_context: Optional[str],
) -> tuple[str, list[str], Optional[str]]:
    """
    Ask Claude Haiku to rate the groundedness and appropriateness of the draft.

    Returns:
        (confidence_level, flags_list, reason_or_None)
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    has_knowledge = bool(knowledge_context and knowledge_context.strip())

    system = (
        "You are a quality-control reviewer for hotel concierge email drafts. "
        "Assess whether the draft reply is appropriate and factually grounded given "
        "the information available. "
        "Respond ONLY with valid JSON — no prose, no markdown fences."
    )

    kb_section = ""
    if has_knowledge:
        kb_section = f"\nKnowledge base content (verified facts):\n{knowledge_context[:3000]}\n"

    user = f"""Hotel: {hotel_name}
Knowledge base provided: {"YES — see below" if has_knowledge else "NO — draft relies on general knowledge only"}
{kb_section}
Guest email subject: {subject}
Guest email (excerpt): {body[:400]}

Draft reply to evaluate:
{draft[:900]}

Return JSON exactly like this:
{{
  "confidence": "high",
  "flags": [],
  "reason": null
}}

Confidence guide:
- "high"   — warm, appropriate, contains no unverifiable specifics (prices, exact hours,
              room availability, named staff, specific policies). Safe to send automatically.
- "medium" — mostly appropriate but contains 1–2 specific claims (prices, hours,
              availability) that are NOT backed by the provided knowledge base.
              Flagged for optional review.
- "low"    — multiple unverified factual claims, advice outside hotel scope,
              confusing wording, or inappropriate tone. Must be reviewed before sending.

flags: short strings describing the issue, e.g. ["specific_price", "unverified_hours"]
reason: one plain-English sentence if confidence is medium or low; otherwise null"""

    try:
        response = client.messages.create(
            model=settings.haiku_model,
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown fences in case the model wraps despite instructions
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)
        confidence = result.get("confidence", CONFIDENCE_MEDIUM)
        if confidence not in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW):
            confidence = CONFIDENCE_MEDIUM
        conf_flags = [str(f) for f in result.get("flags", []) if f]
        reason: Optional[str] = result.get("reason") or None

        logger.info("Confidence check: %s | flags=%s", confidence, conf_flags)
        return confidence, conf_flags, reason

    except Exception as exc:
        logger.warning("Confidence check failed (defaulting to medium): %s", exc)
        return CONFIDENCE_MEDIUM, [], None
