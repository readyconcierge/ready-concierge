"""
pattern_detector.py — Rule-based detection of operationally significant patterns
in aggregated concierge email data.

Patterns detected:
  - volume_spike:      A category receives more emails than its threshold.
  - time_cluster:      3+ arrival/transportation requests within a short window.
  - multi_signal_guest: A guest appears in 2+ distinct intent categories.
  - celebration_cluster: 2+ celebration requests in the window.
  - sentiment_flag:    Email body contains strong negative language.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import get_settings
from modules.signal_aggregator import AggregatedSignal, GuestRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Negative sentiment keyword list (deliberately conservative to reduce noise)
# ---------------------------------------------------------------------------
_NEGATIVE_KEYWORDS = re.compile(
    r"\b("
    r"unacceptable|terrible|horrible|awful|disgusting|furious|outraged|"
    r"disgusted|nightmare|disaster|appalled|demand(ing)? refund|"
    r"never returning|worst|incompetent|useless|ignored|no response|"
    r"complete(ly)? wrong|very disappointed|deeply disappointed|"
    r"not what (i|we) (expected|paid for)|waste of money|"
    r"speak(ing)? to (the )?manager|file (a )?complaint|legal action"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class DetectedPattern:
    """A single detected operational pattern."""
    pattern_type: str        # spike | cluster | sentiment | multi_signal
    category: str
    count: int
    description: str
    priority: str = "normal" # high | normal | low
    affected_guests: list[str] = field(default_factory=list)


@dataclass
class GuestFlag:
    """A guest-level flag for the concierge team's attention."""
    guest_name: str
    guest_email: str
    reason: str
    priority: str = "normal"  # high | normal | low


@dataclass
class DetectionResult:
    """Complete output of the pattern detection pass."""
    patterns: list[DetectedPattern]
    guest_flags: list[GuestFlag]
    has_high_priority: bool = False


def detect_patterns(signal: AggregatedSignal) -> DetectionResult:
    """
    Run all rule-based detectors over an AggregatedSignal.

    Args:
        signal: Pre-aggregated email data for a property and time window.

    Returns:
        DetectionResult with all detected patterns and guest-level flags.
    """
    settings = get_settings()
    patterns: list[DetectedPattern] = []
    flags: list[GuestFlag] = []

    # 1. Volume spikes
    patterns.extend(_detect_volume_spikes(signal, settings))

    # 2. Time clusters (arrival + transportation)
    patterns.extend(_detect_time_clusters(signal, settings))

    # 3. Celebration clusters
    patterns.extend(_detect_celebration_cluster(signal, settings))

    # 4. Multi-signal guests
    new_flags = _detect_multi_signal_guests(signal)
    flags.extend(new_flags)

    # 5. Negative sentiment flags
    new_flags, sentiment_patterns = _detect_sentiment_flags(signal)
    flags.extend(new_flags)
    patterns.extend(sentiment_patterns)

    has_high = any(p.priority == "high" for p in patterns) or any(
        f.priority == "high" for f in flags
    )

    logger.info(
        "Pattern detection complete | property=%d | patterns=%d | flags=%d | high_priority=%s",
        signal.property_id,
        len(patterns),
        len(flags),
        has_high,
    )

    return DetectionResult(
        patterns=patterns,
        guest_flags=flags,
        has_high_priority=has_high,
    )


# ---------------------------------------------------------------------------
# Individual detectors
# ---------------------------------------------------------------------------

def _detect_volume_spikes(
    signal: AggregatedSignal,
    settings,
) -> list[DetectedPattern]:
    """Flag any intent category that exceeds its volume threshold."""
    found = []
    for intent, count in signal.intent_counts.items():
        threshold = (
            settings.volume_spike_dining
            if intent == "dining"
            else settings.volume_spike_default
        )
        if count >= threshold:
            priority = "high" if count >= threshold * 2 else "normal"
            found.append(DetectedPattern(
                pattern_type="spike",
                category=intent,
                count=count,
                description=(
                    f"{count} {intent.replace('_', ' ')} requests received — "
                    f"above threshold of {threshold}."
                ),
                priority=priority,
                affected_guests=[
                    e["sender_email"]
                    for e in signal.emails_by_intent.get(intent, [])
                ],
            ))
    return found


def _detect_time_clusters(
    signal: AggregatedSignal,
    settings,
) -> list[DetectedPattern]:
    """
    Detect 3+ arrival or transportation requests within the cluster window.
    Uses a sliding window over sorted timestamps.
    """
    found = []
    cluster_categories = ["arrival", "transportation"]
    window_hours = settings.time_cluster_window_hours

    for category in cluster_categories:
        emails = sorted(
            signal.emails_by_intent.get(category, []),
            key=lambda e: e["received_at"] or datetime.min,
        )
        if len(emails) < 3:
            continue

        # Sliding window
        for i, anchor in enumerate(emails):
            anchor_time = anchor["received_at"]
            if anchor_time is None:
                continue
            # Ensure timezone-aware comparison
            if anchor_time.tzinfo is None:
                anchor_time = anchor_time.replace(tzinfo=timezone.utc)

            window_end = anchor_time + timedelta(hours=window_hours)
            cluster = [
                e for e in emails[i:]
                if e["received_at"] is not None
                and (
                    e["received_at"].replace(tzinfo=timezone.utc)
                    if e["received_at"].tzinfo is None
                    else e["received_at"]
                ) <= window_end
            ]
            if len(cluster) >= 3:
                found.append(DetectedPattern(
                    pattern_type="cluster",
                    category=category,
                    count=len(cluster),
                    description=(
                        f"{len(cluster)} {category} requests clustered within "
                        f"a {window_hours}-hour window."
                    ),
                    priority="high",
                    affected_guests=[e["sender_email"] for e in cluster],
                ))
                break  # one cluster report per category is sufficient

    return found


def _detect_celebration_cluster(
    signal: AggregatedSignal,
    settings,
) -> list[DetectedPattern]:
    """Flag when 2+ celebration-related requests arrive in the window."""
    count = signal.intent_counts.get("celebration", 0)
    threshold = settings.celebration_cluster_threshold
    if count >= threshold:
        return [DetectedPattern(
            pattern_type="cluster",
            category="celebration",
            count=count,
            description=(
                f"{count} celebration requests received. "
                "Coordinate amenities, room decorations, and F&B proactively."
            ),
            priority="high" if count >= threshold + 2 else "normal",
            affected_guests=[
                e["sender_email"]
                for e in signal.emails_by_intent.get("celebration", [])
            ],
        )]
    return []


def _detect_multi_signal_guests(signal: AggregatedSignal) -> list[GuestFlag]:
    """Flag guests who have sent requests in 2+ distinct intent categories."""
    flags = []
    for guest in signal.multi_intent_guests:
        unique_intents = list(dict.fromkeys(guest.intents))
        intent_str = ", ".join(i.replace("_", " ") for i in unique_intents)
        flags.append(GuestFlag(
            guest_name=guest.name,
            guest_email=guest.email,
            reason=f"Multiple request types: {intent_str}. May require coordinated response.",
            priority="high" if len(unique_intents) >= 3 else "normal",
        ))
    return flags


def _detect_sentiment_flags(
    signal: AggregatedSignal,
) -> tuple[list[GuestFlag], list[DetectedPattern]]:
    """Scan email bodies for strong negative language and flag those guests."""
    flags = []
    patterns = []
    flagged_count = 0

    for email in signal.chronological_emails:
        body = email.get("body") or ""
        if _NEGATIVE_KEYWORDS.search(body):
            flagged_count += 1
            flags.append(GuestFlag(
                guest_name=email["sender_name"] or email["sender_email"],
                guest_email=email["sender_email"],
                reason=(
                    f"Negative sentiment detected in message: \"{email['subject']}\". "
                    "Review and escalate if warranted."
                ),
                priority="high",
            ))

    if flagged_count > 0:
        patterns.append(DetectedPattern(
            pattern_type="sentiment",
            category="complaint",
            count=flagged_count,
            description=(
                f"{flagged_count} email(s) contain strong negative language. "
                "Immediate review recommended."
            ),
            priority="high",
        ))

    return flags, patterns
