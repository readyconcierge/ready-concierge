"""
draft_generator.py â Generate context-adaptive reply drafts via Claude.

Works for concierge emails, sales inquiries, GM correspondence, and more.
The forwarder simply forwards any email; Claude drafts the reply.
Uses claude-haiku for speed; prompt loaded from prompts/draft_reply.txt.
"""

import logging
from pathlib import Path

import anthropic

from config import get_settings

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "draft_reply.txt"


def _load_system_prompt() -> str:
    """Load the draft reply system prompt from disk."""
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.error("Draft reply prompt not found at %s", _PROMPT_PATH)
        raise


# Intents that benefit from Sonnet's higher emotional intelligence
_SONNET_INTENTS = {"complaint", "vip_request"}


def _select_model(intents: list[str]) -> str:
    """
    Route to the appropriate Claude model based on email complexity.

    Sonnet for: complaints, VIP requests, and multi-intent (3+) emails
    where the extra nuance justifies the cost.
    Haiku for: everything else (fast, cost-efficient).
    """
    settings = get_settings()

    if any(i in _SONNET_INTENTS for i in intents):
        logger.info("Model routing: using Sonnet for intents=%s", intents)
        return settings.sonnet_model

    if len(intents) >= 3:
        logger.info("Model routing: using Sonnet for multi-intent email (%d intents)", len(intents))
        return settings.sonnet_model

    return settings.haiku_model


def generate_draft(
    sender_name: str,
    subject: str,
    body: str,
    intents: list[str],
    hotel_name: str,
    forwarder_context: str | None = None,
    knowledge_context: str | None = None,
    guest_context: str | None = None,
) -> str:
    """
    Generate a context-adaptive reply draft for any email.

    Args:
        sender_name:        Original sender's display name.
        subject:            Email subject line.
        body:               Plain-text email body.
        intents:            Classified intent labels (for context).
        hotel_name:         Hotel/company name for the signature.
        forwarder_context:  Optional context about who forwarded and why.
        knowledge_context:  Optional formatted knowledge-base excerpt (RAG).
        guest_context:      Optional guest history context (memory).

    Returns:
        A polished draft reply string ready to be reviewed and sent.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    system_prompt = _load_system_prompt()

    model = _select_model(intents)
    intent_str = ", ".join(intents) if intents else "general_inquiry"

    # Extract a usable first name for the greeting
    clean_name = sender_name.strip() if sender_name else ""
    # Handle "Last, First (Extra)" format from Outlook
    if "," in clean_name:
        parts = clean_name.split(",", 1)
        clean_name = parts[1].strip().split("(")[0].strip() + " " + parts[0].strip()

    user_message = (
        f"Organization: {hotel_name}\n"
        f"Original Sender: {clean_name or 'Unknown'}\n"
        f"Request Type(s): {intent_str}\n"
        f"Subject: {subject}\n"
    )
    if forwarder_context:
        user_message += f"Context: {forwarder_context}\n"
    if guest_context:
        user_message += f"\n{guest_context}\n"
    if knowledge_context:
        user_message += f"\n{knowledge_context}\n"
    user_message += f"\nOriginal Email:\n{body}"

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        draft = response.content[0].text.strip()
        logger.info(
            "Draft generated for sender %r | model=%s | intents=%s | length=%d chars",
            sender_name,
            model,
            intent_str,
            len(draft),
        )
        return draft

    except anthropic.APIError as exc:
        logger.error("Anthropic API error generating draft for %r: %s", sender_name, exc)
        raise
    except Exception as exc:
        logger.error("Unexpected error generating draft: %s", exc)
        raise
