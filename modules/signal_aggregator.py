"""
signal_aggregator.py — Aggregate inbound emails over a time window for signal generation.

Groups emails by intent category, identifies multi-intent guests,
and builds the structured data that pattern_detector.py and signal_generator.py consume.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from database import Email, Property

logger = logging.getLogger(__name__)


@dataclass
class GuestRecord:
    """Represents a single guest's email activity within the time window."""
    name: str
    email: str
    intents: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)
    received_at: list[datetime] = field(default_factory=list)


@dataclass
class AggregatedSignal:
    """Structured aggregation of emails over a time window."""
    property_id: int
    hotel_name: str
    time_window_start: datetime
    time_window_end: datetime
    total_emails: int
    emails_by_intent: dict[str, list[dict]]          # intent → list of email dicts
    intent_counts: dict[str, int]                     # intent → count
    guests: dict[str, GuestRecord]                    # email → GuestRecord
    multi_intent_guests: list[GuestRecord]            # guests with 2+ intent categories
    chronological_emails: list[dict]                  # all emails sorted by received_at


def aggregate_for_property(
    db: Session,
    property_obj: Property,
    hours_back: int = 24,
    end_time: Optional[datetime] = None,
) -> AggregatedSignal:
    """
    Collect and structure all emails for a property within a lookback window.

    Args:
        db:            Active database session.
        property_obj:  The property to aggregate for.
        hours_back:    How many hours to look back (24 for daily, 1-3 for hourly).
        end_time:      End of the window (defaults to now UTC).

    Returns:
        An AggregatedSignal dataclass ready for pattern detection.
    """
    if end_time is None:
        end_time = datetime.now(timezone.utc)

    # Make end_time timezone-aware if naive
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    start_time = end_time - timedelta(hours=hours_back)

    # Fetch emails in the window
    emails_q = (
        db.query(Email)
        .filter(
            Email.property_id == property_obj.id,
            Email.received_at >= start_time,
            Email.received_at <= end_time,
        )
        .order_by(Email.received_at.asc())
        .all()
    )

    logger.info(
        "Aggregating %d emails for property %r (%s to %s)",
        len(emails_q),
        property_obj.hotel_name,
        start_time.isoformat(),
        end_time.isoformat(),
    )

    # --- Build intent buckets and guest records ---------------------------
    emails_by_intent: dict[str, list[dict]] = defaultdict(list)
    intent_counts: dict[str, int] = defaultdict(int)
    guests: dict[str, GuestRecord] = {}
    chronological: list[dict] = []

    for email in emails_q:
        intents = email.intents  # uses the property on the model

        email_dict = {
            "id": email.id,
            "sender_name": email.sender_name,
            "sender_email": email.sender_email,
            "subject": email.subject,
            "body": email.body,
            "received_at": email.received_at,
            "intents": intents,
        }
        chronological.append(email_dict)

        for intent in intents:
            emails_by_intent[intent].append(email_dict)
            intent_counts[intent] += 1

        # Track per-guest
        key = email.sender_email.lower()
        if key not in guests:
            guests[key] = GuestRecord(
                name=email.sender_name or key,
                email=key,
            )
        record = guests[key]
        record.intents.extend(intents)
        record.subjects.append(email.subject or "")
        record.bodies.append(email.body or "")
        if email.received_at:
            record.received_at.append(email.received_at)

    # De-duplicate intent lists per guest (preserve uniqueness)
    for record in guests.values():
        record.intents = list(dict.fromkeys(record.intents))  # ordered dedup

    # Multi-intent guests: have 2+ distinct intent categories
    multi_intent = [r for r in guests.values() if len(set(r.intents)) >= 2]

    return AggregatedSignal(
        property_id=property_obj.id,
        hotel_name=property_obj.hotel_name,
        time_window_start=start_time,
        time_window_end=end_time,
        total_emails=len(emails_q),
        emails_by_intent=dict(emails_by_intent),
        intent_counts=dict(intent_counts),
        guests=guests,
        multi_intent_guests=multi_intent,
        chronological_emails=chronological,
    )
