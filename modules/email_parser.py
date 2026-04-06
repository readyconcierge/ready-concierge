"""
email_parser.py — Parse inbound webhook payloads from SendGrid Inbound Parse.

SendGrid POSTs multipart/form-data with fields including:
  from, to, subject, text, html, headers, envelope, charsets, etc.

We normalize the payload into a clean dict for downstream processing.
Also detects forwarded emails and extracts original sender/subject/body
from Gmail, Outlook, and Apple Mail forward formats.
"""

import json
import logging
import re
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any

logger = logging.getLogger(__name__)

# SendGrid uses "text"; Mailgun used "stripped-text" / "body-plain"
_BODY_FIELD_PRIORITY = ["text", "stripped-text", "body-plain", "body-html"]

# ---------------------------------------------------------------------------
# Forwarded email detection patterns (unused compiled regexes removed;
# detection uses line-by-line parsing in extract_forwarded_content)
# ---------------------------------------------------------------------------

# Outlook / Apple Mail: "From: ... Sent: ... To: ... Subject: ..."
_OUTLOOK_FWD_RE = re.compile(
    r"From:\s*(?P<from>.+?)\n"
    r"(?:Sent|Date):\s*.+?\n"
    r"To:\s*.+?\n"
    r"(?:Cc:.*?\n)?"
    r"Subject:\s*(?P<subject>.+?)\n"
    r"\n(?P<body>[\s\S]+)",
    re.IGNORECASE,
)


def parse_inbound_email(form_data: dict[str, Any]) -> dict[str, Any]:
    """
    Parse a SendGrid Inbound Parse webhook form payload into a normalized dict.

    Args:
        form_data: Raw key-value pairs from the multipart POST body.

    Returns:
        A dict with keys: message_id, sender_name, sender_email,
        recipient, subject, body, received_at.

    Raises:
        ValueError: If required fields are missing or unparseable.
    """
    # --- Sender -----------------------------------------------------------
    raw_from = (
        form_data.get("from")
        or form_data.get("From")
        or form_data.get("sender", "")
    )

    # SendGrid also provides an "envelope" JSON field with clean addresses
    envelope = _parse_envelope(form_data.get("envelope", ""))
    if not raw_from and envelope.get("from"):
        raw_from = envelope["from"]

    sender_name, sender_email = _parse_address(raw_from)

    if not sender_email:
        sender_email = (form_data.get("sender") or "").strip().lower()
        if not sender_email:
            raise ValueError("Cannot determine sender email from webhook payload.")

    # --- Recipient --------------------------------------------------------
    raw_recipient = (
        form_data.get("to")
        or form_data.get("To")
        or form_data.get("recipient")
        or form_data.get("Recipient")
        or ""
    )
    # envelope["to"] is a list
    if not raw_recipient and envelope.get("to"):
        raw_recipient = envelope["to"][0] if envelope["to"] else ""

    _, recipient_email = _parse_address(raw_recipient)

    # --- Subject ----------------------------------------------------------
    subject = (
        form_data.get("subject")
        or form_data.get("Subject")
        or "(no subject)"
    ).strip()

    # --- Body -------------------------------------------------------------
    body = ""
    for field in _BODY_FIELD_PRIORITY:
        candidate = form_data.get(field, "").strip()
        if candidate:
            body = _clean_body(candidate)
            break

    if not body:
        logger.warning(
            "Inbound email has no readable body (from: %s)", sender_email
        )

    # --- Message ID -------------------------------------------------------
    # SendGrid does not give a separate Message-Id field; extract from headers
    message_id = (
        form_data.get("Message-Id")
        or form_data.get("message-id")
        or _extract_message_id_from_headers(form_data.get("headers", ""))
        or f"unknown-{int(datetime.now(timezone.utc).timestamp())}"
    ).strip()

    # --- Timestamp --------------------------------------------------------
    # SendGrid doesn't pass a Unix timestamp; pull Date from raw headers
    ts_raw = (
        form_data.get("timestamp")
        or form_data.get("Date")
        or _extract_header_value(form_data.get("headers", ""), "Date")
        or ""
    )
    received_at = _parse_timestamp(ts_raw)

    result = {
        "message_id": message_id,
        "sender_name": sender_name or _extract_name_from_email(sender_email),
        "sender_email": sender_email.lower(),
        "recipient": recipient_email.lower() if recipient_email else "",
        "subject": subject,
        "body": body,
        "received_at": received_at,
        "forwarded": None,  # populated below if this is a forwarded email
    }

    # --- Detect forwarded content -----------------------------------------
    if body:
        fwd = extract_forwarded_content(body)
        if fwd:
            result["forwarded"] = fwd
            logger.info(
                "Forwarded email detected | original_sender=%s | original_subject=%r",
                fwd.get("original_sender_email"),
                fwd.get("original_subject"),
            )

    logger.info(
        "Parsed email | from=%s | subject=%r | body_len=%d | forwarded=%s",
        result["sender_email"],
        result["subject"],
        len(result["body"]),
        bool(result["forwarded"]),
    )
    return result


# ---------------------------------------------------------------------------
# Forwarded email extraction
# ---------------------------------------------------------------------------

def extract_forwarded_content(body: str) -> dict[str, Any] | None:
    """
    Detect and extract original sender/subject/body from a forwarded email.

    Supports Gmail ("---------- Forwarded message ---------"),
    Outlook / Apple Mail ("From: ... Sent: ... Subject: ...") formats.

    Returns a dict with keys:
        original_sender_raw, original_sender_name, original_sender_email,
        original_subject, original_body
    or None if the body does not appear to be a forwarded message.
    """
    lines = body.splitlines()

    # Find the start of the forwarded block
    fwd_start = None
    fwd_type = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Gmail: "---------- Forwarded message ---------"
        if re.match(r"-{5,}\s*Forwarded message\s*-{5,}", stripped, re.IGNORECASE):
            fwd_start = i
            fwd_type = "gmail"
            break
        # Outlook/Apple: "Begin forwarded message:" or "----Original Message----"
        if re.match(r"(begin forwarded message|original message)", stripped, re.IGNORECASE):
            fwd_start = i
            fwd_type = "outlook"
            break

    if fwd_start is None:
        # Check for inline Outlook-style forward block (From/Sent/To/Subject header block)
        # Look for a "From:" line followed by "Sent:" or "Date:" and "Subject:" nearby
        for i, line in enumerate(lines):
            if re.match(r"From:\s*.+", line, re.IGNORECASE):
                window = lines[i:i+6]
                has_date = any(re.match(r"(Sent|Date):\s*", l, re.IGNORECASE) for l in window)
                has_subj = any(re.match(r"Subject:\s*", l, re.IGNORECASE) for l in window)
                if has_date and has_subj:
                    fwd_start = i
                    fwd_type = "outlook_inline"
                    break

    if fwd_start is None:
        return None

    # Parse the header block after the forwarded marker
    block = lines[fwd_start:]
    if fwd_type == "gmail":
        # Skip the "---------- Forwarded message" line itself
        block = block[1:]

    raw_from = ""
    subject = ""
    body_start = None

    for i, line in enumerate(block):
        stripped = line.strip()
        if re.match(r"From:\s*", stripped, re.IGNORECASE):
            raw_from = re.sub(r"^From:\s*", "", stripped, flags=re.IGNORECASE).strip()
        elif re.match(r"Subject:\s*", stripped, re.IGNORECASE):
            subject = re.sub(r"^Subject:\s*", "", stripped, flags=re.IGNORECASE).strip()
        elif stripped == "" and raw_from:
            # Blank line after headers = body starts next
            body_start = i + 1
            break

    if not raw_from:
        return None

    fwd_body = ""
    if body_start is not None:
        fwd_body = _clean_body("\n".join(block[body_start:]))

    name, email = _parse_address(raw_from)
    return {
        "original_sender_raw": raw_from,
        "original_sender_name": name or _extract_name_from_email(email),
        "original_sender_email": email.lower() if email else "",
        "original_subject": subject,
        "original_body": fwd_body,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_address(raw: str) -> tuple[str, str]:
    """Return (display_name, email) from a raw RFC 2822 address string."""
    if not raw:
        return "", ""
    name, email = parseaddr(raw)
    return name.strip(), email.strip().lower()


def _parse_envelope(raw: str) -> dict:
    """Parse SendGrid's JSON envelope field."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _extract_message_id_from_headers(headers_raw: str) -> str:
    """Extract Message-Id value from a raw headers block."""
    return _extract_header_value(headers_raw, "Message-Id") or \
           _extract_header_value(headers_raw, "Message-ID")


def _extract_header_value(headers_raw: str, header_name: str) -> str:
    """Extract a single header value from a raw headers string."""
    if not headers_raw:
        return ""
    pattern = rf"^{re.escape(header_name)}:\s*(.+)$"
    match = re.search(pattern, headers_raw, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _parse_timestamp(raw: str) -> datetime:
    """Convert a Unix timestamp string or RFC 2822 date to a UTC datetime."""
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        logger.warning("Could not parse timestamp %r, using now.", raw)
        return datetime.now(timezone.utc)


def _clean_body(text: str) -> str:
    """Strip excessive whitespace from email body text."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _extract_name_from_email(email: str) -> str:
    """Best-effort: turn 'john.smith@example.com' → 'John Smith'."""
    local = email.split("@")[0] if "@" in email else email
    parts = re.split(r"[._\-+]", local)
    return " ".join(p.capitalize() for p in parts if p)
