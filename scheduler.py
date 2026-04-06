"""
scheduler.py — APScheduler-based cron jobs for signal generation.

On startup, loads all streams with signal_enabled=True and schedules:
  - signal_frequency = "daily"  → runs at signal_send_time (e.g. "06:00")
  - signal_frequency = "hourly" → runs every hour

The scheduler is wired into the FastAPI lifespan so it starts and stops
cleanly with the application.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from database import Stream, SessionLocal, get_db
from modules.signal_aggregator import aggregate_for_property
from modules.pattern_detector import detect_patterns
from modules.signal_generator import generate_signal_briefing
from modules.signal_sender import send_signal_email
from modules.gm_digest import generate_weekly_digest, send_gm_digest

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def run_signal_for_stream(stream_id: int, hours_back: int = 24) -> dict | None:
    """
    Execute the full signal pipeline for one stream.

    Args:
        stream_id:  Database ID of the stream.
        hours_back: Time window to look back (24 for daily, 1 for hourly).

    Returns:
        The generated briefing dict, or None on failure.
    """
    db: Session = SessionLocal()
    try:
        stream = db.query(Stream).filter(Stream.id == stream_id).first()
        if not stream:
            logger.error("Signal job: stream %d not found.", stream_id)
            return None

        logger.info(
            "Running signal pipeline for %r (stream_id=%d, hours_back=%d)",
            stream.hotel_name,
            stream_id,
            hours_back,
        )

        signal = aggregate_for_property(db, stream, hours_back=hours_back)

        if signal.total_emails == 0:
            logger.info("No emails in window for %r — skipping signal.", stream.hotel_name)
            return None

        detection = detect_patterns(signal)
        briefing = generate_signal_briefing(signal, detection)

        # Persist snapshot
        from database import SignalSnapshot, SignalPattern, SignalFlag
        import json

        snapshot = SignalSnapshot(
            property_id=stream.id,
            stream_id=stream.id,
            time_window_start=signal.time_window_start,
            time_window_end=signal.time_window_end,
            total_emails=signal.total_emails,
            system_state=briefing.get("system_state", ""),
            generated_summary=json.dumps(briefing),
            confidence=briefing.get("confidence", "low"),
        )
        db.add(snapshot)
        db.flush()

        for p in detection.patterns:
            db.add(SignalPattern(
                snapshot_id=snapshot.id,
                pattern_type=p.pattern_type,
                category=p.category,
                count=p.count,
                description=p.description,
            ))

        for f in detection.guest_flags:
            db.add(SignalFlag(
                snapshot_id=snapshot.id,
                guest_name=f.guest_name,
                guest_email=f.guest_email,
                reason=f.reason,
                priority=f.priority,
            ))

        db.commit()

        # Send the signal email
        recipients = stream.signal_recipients
        if recipients:
            send_signal_email(
                recipient_emails=recipients,
                hotel_name=stream.hotel_name,
                briefing=briefing,
                time_window_start=signal.time_window_start,
                time_window_end=signal.time_window_end,
            )
        else:
            logger.warning("No signal recipients configured for %r.", stream.hotel_name)

        return briefing

    except Exception as exc:
        logger.error("Signal pipeline error for stream %d: %s", stream_id, exc, exc_info=True)
        db.rollback()
        return None
    finally:
        db.close()


# Legacy alias for any callers that still use the old name
run_signal_for_property = run_signal_for_stream


async def run_weekly_gm_digest(stream_id: int) -> dict | None:
    """
    Generate and send the weekly GM intelligence digest for a stream.

    Sends to all signal recipients (staff + GM).
    Runs every Monday at 07:00 UTC by default.
    """
    db = SessionLocal()
    try:
        stream = db.query(Stream).filter(Stream.id == stream_id).first()
        if not stream:
            logger.error("Weekly GM digest: stream %d not found", stream_id)
            return None

        logger.info("Generating weekly GM digest for %r (stream_id=%d)", stream.hotel_name, stream_id)

        digest = generate_weekly_digest(stream_id=stream_id, days_back=7)
        if not digest:
            logger.info("Weekly GM digest: no data for stream %d — skipping", stream_id)
            return None

        # Send to all signal recipients (includes staff + GM)
        recipients = stream.signal_recipients
        if not recipients:
            logger.warning("No recipients for GM digest on stream %d", stream_id)
            return digest

        send_gm_digest(recipient_emails=recipients, digest=digest)
        return digest

    except Exception as exc:
        logger.error("Weekly GM digest error for stream %d: %s", stream_id, exc, exc_info=True)
        return None
    finally:
        db.close()


def _schedule_stream(scheduler: AsyncIOScheduler, stream: Stream) -> None:
    """Add the appropriate APScheduler job for a single stream."""
    job_id_base = f"signal_stream_{stream.id}"

    if stream.signal_frequency == "hourly":
        scheduler.add_job(
            run_signal_for_stream,
            trigger=IntervalTrigger(hours=1),
            id=f"{job_id_base}_hourly",
            name=f"Hourly Signal: {stream.hotel_name}",
            kwargs={"stream_id": stream.id, "hours_back": 1},
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("Scheduled hourly signal for stream %d (%s)", stream.id, stream.hotel_name)

    else:  # daily (default)
        try:
            hour, minute = [int(x) for x in (stream.signal_send_time or "06:00").split(":")]
        except (ValueError, AttributeError):
            logger.warning(
                "Invalid signal_send_time %r for stream %d — defaulting to 06:00.",
                stream.signal_send_time,
                stream.id,
            )
            hour, minute = 6, 0

        scheduler.add_job(
            run_signal_for_stream,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
            id=f"{job_id_base}_daily",
            name=f"Daily Signal: {stream.hotel_name}",
            kwargs={"stream_id": stream.id, "hours_back": 24},
            replace_existing=True,
            misfire_grace_time=600,
        )
        logger.info(
            "Scheduled daily signal for stream %d (%s) at %02d:%02d UTC",
            stream.id,
            stream.hotel_name,
            hour,
            minute,
        )

    # Always schedule the weekly GM digest (Monday 07:00 UTC)
    scheduler.add_job(
        run_weekly_gm_digest,
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=0, timezone="UTC"),
        id=f"{job_id_base}_weekly_gm",
        name=f"Weekly GM Digest: {stream.hotel_name}",
        kwargs={"stream_id": stream.id},
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduled weekly GM digest for stream %d (%s) — Monday 07:00 UTC", stream.id, stream.hotel_name)


# Legacy alias
def _schedule_property(scheduler: AsyncIOScheduler, prop) -> None:
    _schedule_stream(scheduler, prop)


def init_scheduler() -> AsyncIOScheduler:
    """
    Create the scheduler, register all active stream jobs, and return it.
    Call start() on the returned scheduler to begin execution.
    """
    global _scheduler

    scheduler = AsyncIOScheduler(timezone="UTC")

    db: Session = SessionLocal()
    try:
        streams = (
            db.query(Stream)
            .filter(Stream.signal_enabled.is_(True))
            .all()
        )
        logger.info("Initialising scheduler with %d active streams.", len(streams))
        for stream in streams:
            _schedule_stream(scheduler, stream)
    finally:
        db.close()

    _scheduler = scheduler
    return scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    """Return the singleton scheduler instance."""
    return _scheduler


def reschedule_stream(stream: Stream) -> None:
    """
    Add or update the signal job for a stream at runtime.
    Safe to call after the scheduler is already running.
    """
    if _scheduler is None:
        logger.warning("Scheduler not initialised — cannot reschedule stream %d.", stream.id)
        return
    _schedule_stream(_scheduler, stream)


# Legacy alias
def reschedule_property(prop) -> None:
    reschedule_stream(prop)
