"""
main.py — FastAPI application entrypoint for Ready Concierge.

Architecture: Company → Property → Stream
  Each Stream is an independent operational channel (e.g. Concierge, Spa).
  All API routes that operate on emails / tasks / signals / knowledge
  are scoped to a stream_id.

Endpoints:
  POST /webhook/inbound              — SendGrid inbound email webhook
  POST /signal/trigger               — Manually trigger signal for a stream
  GET  /health                       — Health check
  GET  /api/properties               — List all properties (with stream counts)
  GET  /api/streams/{property_id}    — List streams for a property
  POST /api/streams                  — Create a new stream
  GET  /api/tasks/{stream_id}        — Tasks for a stream
  PATCH /api/tasks/{task_id}         — Mark a task complete / incomplete
  GET  /api/emails/{stream_id}       — Email history for a stream
  GET  /api/review/{stream_id}       — Review queue for a stream
  POST /api/review/{draft_id}/approve
  POST /api/review/{draft_id}/reject
  POST /api/emails/{email_id}/draft  — Generate on-demand draft
  POST /api/knowledge/{stream_id}/upload
  GET  /api/knowledge/{stream_id}
  DELETE /api/knowledge/{stream_id}/{doc_id}
  POST /api/knowledge/{stream_id}/search
"""

import json
import logging
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings
from database import (
    CommittedTask, Company, DraftFeedback, DraftReply, Email,
    GuestInteraction, KnowledgeDocument,
    Property, Stream, get_db, init_db,
)
from modules.digest_sender import DIGEST_SUBJECT_PREFIX, parse_done_reply, send_digest
from modules.draft_generator import generate_draft
from modules.draft_sender import send_draft_to_staff, send_reply_to_guest
from modules.email_parser import extract_forwarded_content, parse_inbound_email
from modules.guardrails import evaluate_draft as run_guardrails
from modules.guest_memory import build_guest_context, lookup_guest_history, record_interaction
from modules.intent_classifier import classify_intent
from modules.knowledge import get_relevant_context, ingest_document
from modules.task_extractor import extract_tasks
from scheduler import init_scheduler, run_signal_for_stream, run_weekly_gm_digest

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise DB and scheduler on startup; shut down cleanly on exit."""
    logger.info("Ready Concierge starting up…")
    init_db()

    scheduler = init_scheduler()
    scheduler.start()
    logger.info("Scheduler started.")

    yield

    logger.info("Ready Concierge shutting down…")
    scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Ready Concierge",
    description="AI concierge email copilot + signal layer for luxury hotels.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets (venue photos, etc.)
import pathlib as _pathlib
_static_dir = _pathlib.Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class SignalTriggerRequest(BaseModel):
    stream_id: int
    hours_back: int = 24


class CreateStreamRequest(BaseModel):
    property_id: int
    name: str                      # e.g. "Spa"
    display_name: str              # e.g. "Park Hyatt Aviara — Spa"
    inbound_email: str
    staff_email: str
    signal_enabled: bool = True
    signal_frequency: str = "daily"
    signal_send_time: str = "06:00"
    signal_recipient_emails: list[str] = []


# ---------------------------------------------------------------------------
# System routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health_check():
    """Returns 200 OK if the service is running."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Public pages — guest-facing content linked from draft emails
# ---------------------------------------------------------------------------

@app.get("/dining/private-events", tags=["Public Pages"], response_class=HTMLResponse)
async def dining_private_events():
    """Serve the beautifully formatted private dining & large party options page."""
    html_path = _pathlib.Path(__file__).parent / "static" / "dining-private-events.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)


# ---------------------------------------------------------------------------
# Feedback — one-click draft quality feedback from email links
# ---------------------------------------------------------------------------

def _generate_feedback_token() -> str:
    """Generate a unique, URL-safe feedback token."""
    import secrets
    return secrets.token_urlsafe(32)


@app.get("/api/feedback/{token}/{verdict}", tags=["Feedback"])
async def record_draft_feedback(token: str, verdict: str, db: Session = Depends(get_db)):
    """
    One-click feedback endpoint embedded in draft emails.

    Staff click "This was perfect" or "This needed changes" and land here.
    Returns a simple HTML thank-you page (no login required).
    """
    if verdict not in ("perfect", "changed"):
        return HTMLResponse("<h2>Invalid feedback link.</h2>", status_code=400)

    draft = db.query(DraftReply).filter(DraftReply.feedback_token == token).first()
    if not draft:
        return HTMLResponse(
            "<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
            "<h2>Link expired or already used.</h2>"
            "<p style='color:#888;'>This feedback link is no longer valid.</p>"
            "</body></html>",
            status_code=404,
        )

    # Check if feedback already recorded for this draft
    existing = db.query(DraftFeedback).filter(DraftFeedback.draft_reply_id == draft.id).first()
    if existing:
        return HTMLResponse(
            "<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
            "<h2>Thanks! Your feedback was already recorded.</h2>"
            "<p style='color:#888;'>You rated this draft earlier.</p>"
            "</body></html>",
        )

    # Record the feedback
    email = db.query(Email).filter(Email.id == draft.email_id).first()
    feedback = DraftFeedback(
        draft_reply_id=draft.id,
        email_id=draft.email_id,
        stream_id=email.stream_id if email else None,
        verdict=verdict,
    )
    db.add(feedback)

    # Also update the DraftReply.accepted column
    draft.accepted = (verdict == "perfect")
    db.commit()

    # Update guest interaction feedback if applicable
    if email and email.sender_email:
        interaction = (
            db.query(GuestInteraction)
            .filter(
                GuestInteraction.guest_email == email.sender_email.lower(),
                GuestInteraction.stream_id == email.stream_id,
            )
            .order_by(GuestInteraction.interaction_at.desc())
            .first()
        )
        if interaction:
            interaction.feedback = verdict
            db.commit()

    logger.info("Feedback recorded | draft_id=%d | verdict=%s", draft.id, verdict)

    emoji = "🎯" if verdict == "perfect" else "📝"
    message = "Glad to hear it!" if verdict == "perfect" else "Got it — we'll keep improving."

    return HTMLResponse(
        f"<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
        f"<p style='font-size:48px;margin-bottom:8px;'>{emoji}</p>"
        f"<h2 style='color:#0a1628;'>Feedback recorded</h2>"
        f"<p style='color:#888;font-size:16px;'>{message}</p>"
        f"</body></html>"
    )


# ---------------------------------------------------------------------------
# One-click Send Reply — sends the draft directly to the guest (threaded)
# ---------------------------------------------------------------------------

@app.get("/api/draft/{draft_id}/send", tags=["Draft Reply"])
async def send_draft_reply_to_guest(draft_id: int, db: Session = Depends(get_db)):
    """
    One-click send endpoint embedded in draft emails.

    Staff click "Send Reply" and this sends the draft directly to the guest
    as a threaded reply (using In-Reply-To / References headers).
    Returns a simple HTML confirmation page.
    """
    draft = db.query(DraftReply).filter(DraftReply.id == draft_id).first()
    if not draft:
        return HTMLResponse(
            "<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
            "<h2>Draft not found.</h2>"
            "<p style='color:#888;'>This draft may have been deleted.</p>"
            "</body></html>",
            status_code=404,
        )

    # Check if already sent to guest
    if draft.reviewer_action == "sent_to_guest":
        return HTMLResponse(
            "<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
            "<p style='font-size:48px;margin-bottom:8px;'>✅</p>"
            "<h2 style='color:#0a1628;'>Already sent!</h2>"
            "<p style='color:#888;font-size:16px;'>This reply was already sent to the guest.</p>"
            "</body></html>",
        )

    # Look up the original email for threading info
    email = db.query(Email).filter(Email.id == draft.email_id).first()
    if not email:
        return HTMLResponse(
            "<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
            "<h2>Original email not found.</h2>"
            "<p style='color:#888;'>Cannot send reply — the original email record is missing.</p>"
            "</body></html>",
            status_code=404,
        )

    # Verify we have a guest email to send to
    if not email.sender_email or "@" not in email.sender_email:
        logger.warning(
            "Draft %d has no guest email — cannot send | sender_email=%r",
            draft.id, email.sender_email,
        )
        return HTMLResponse(
            "<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
            "<p style='font-size:48px;margin-bottom:8px;'>📧</p>"
            "<h2 style='color:#0a1628;'>No guest email address</h2>"
            "<p style='color:#888;font-size:16px;'>The original sender's email could not be extracted from the forwarded message. "
            "Please use the email fallback link to reply manually.</p>"
            "</body></html>",
            status_code=422,
        )

    # Get the stream for the from-address
    stream = db.query(Stream).filter(Stream.id == email.stream_id).first()
    from_email = stream.inbound_email if stream else get_settings().sendgrid_from_email
    from_name = stream.display_name if stream else "Ready Concierge"

    # Send the threaded reply
    success, error_detail = send_reply_to_guest(
        guest_email=email.sender_email,
        guest_name=email.sender_name or "",
        original_subject=email.subject or "",
        original_message_id=email.message_id or "",
        draft_text=draft.draft_text,
        from_email=from_email,
        from_name=from_name,
    )

    if success:
        draft.reviewer_action = "sent_to_guest"
        draft.reviewed_at = datetime.now(timezone.utc)
        # Also record as "perfect" feedback since they approved it by sending
        draft.accepted = True
        db.commit()

        logger.info(
            "Draft %d sent to guest %s via one-click send | subject=%r",
            draft.id, email.sender_email, email.subject,
        )

        return HTMLResponse(
            "<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
            "<p style='font-size:48px;margin-bottom:8px;'>✉️</p>"
            "<h2 style='color:#0a1628;'>Reply sent!</h2>"
            f"<p style='color:#888;font-size:16px;'>Your reply has been sent to {_esc_html(email.sender_name or email.sender_email)}.</p>"
            "<p style='color:#aaa;font-size:13px;margin-top:16px;'>The reply will appear in their inbox as part of the original conversation.</p>"
            "</body></html>"
        )
    else:
        logger.error(
            "Draft %d send failed | guest=%s | error=%s",
            draft.id, email.sender_email, error_detail,
        )
        return HTMLResponse(
            "<html><body style='font-family:Georgia,serif;max-width:500px;margin:80px auto;text-align:center;'>"
            "<p style='font-size:48px;margin-bottom:8px;'>⚠️</p>"
            "<h2 style='color:#0a1628;'>Send failed</h2>"
            f"<p style='color:#888;font-size:16px;'>Error: {_esc_html(error_detail)}</p>"
            "<p style='color:#aaa;font-size:13px;margin-top:16px;'>Please try again or use the mailto fallback.</p>"
            "</body></html>",
            status_code=500,
        )


def _esc_html(text: str) -> str:
    """Minimal HTML escaping for inline text."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Property / Stream management
# ---------------------------------------------------------------------------

@app.get("/api/properties", tags=["Properties"])
async def list_properties(db: Session = Depends(get_db)):
    """
    List all properties with their streams and aggregate stats.
    Used by the dashboard property overview page.
    """
    properties = db.query(Property).order_by(Property.id).all()
    result = []
    for prop in properties:
        streams_data = []
        for stream in prop.streams:
            pending_tasks = db.query(CommittedTask).filter(
                CommittedTask.stream_id == stream.id,
                CommittedTask.completed == False,
            ).count()
            from datetime import timedelta
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            emails_today = db.query(Email).filter(
                Email.stream_id == stream.id,
                Email.received_at >= today_start,
            ).count()
            review_count = (
                db.query(DraftReply)
                .join(Email, DraftReply.email_id == Email.id)
                .filter(
                    Email.stream_id == stream.id,
                    DraftReply.needs_review == True,
                    DraftReply.reviewer_action == None,
                )
                .count()
            )
            streams_data.append({
                "id": stream.id,
                "name": stream.name,
                "display_name": stream.display_name,
                "inbound_email": stream.inbound_email,
                "staff_email": stream.staff_email,
                "signal_enabled": stream.signal_enabled,
                "signal_frequency": stream.signal_frequency,
                "signal_send_time": stream.signal_send_time,
                "pending_tasks": pending_tasks,
                "emails_today": emails_today,
                "review_queue": review_count,
            })
        result.append({
            "id": prop.id,
            "name": prop.name,
            "company_id": prop.company_id,
            "streams": streams_data,
            "stream_count": len(streams_data),
        })
    return JSONResponse({"properties": result})


@app.get("/api/streams/{property_id}", tags=["Properties"])
async def list_streams(property_id: int, db: Session = Depends(get_db)):
    """List all streams for a property."""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail=f"Property {property_id} not found.")
    streams = db.query(Stream).filter(Stream.property_id == property_id).order_by(Stream.id).all()
    return JSONResponse({
        "property_id": property_id,
        "property_name": prop.name,
        "streams": [
            {
                "id": s.id,
                "name": s.name,
                "display_name": s.display_name,
                "inbound_email": s.inbound_email,
                "staff_email": s.staff_email,
                "signal_enabled": s.signal_enabled,
                "signal_frequency": s.signal_frequency,
                "signal_send_time": s.signal_send_time,
            }
            for s in streams
        ],
    })


@app.post("/api/streams", tags=["Properties"], status_code=status.HTTP_201_CREATED)
async def create_stream(payload: CreateStreamRequest, db: Session = Depends(get_db)):
    """
    Create a new stream under a property.

    Use this to add departments like Spa, Restaurant Events, etc.
    """
    prop = db.query(Property).filter(Property.id == payload.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail=f"Property {payload.property_id} not found.")

    existing = db.query(Stream).filter(Stream.inbound_email == payload.inbound_email).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Inbound email {payload.inbound_email!r} already in use.")

    stream = Stream(
        property_id=prop.id,
        company_id=prop.company_id,
        name=payload.name,
        display_name=payload.display_name,
        inbound_email=payload.inbound_email,
        staff_email=payload.staff_email,
        signal_enabled=payload.signal_enabled,
        signal_frequency=payload.signal_frequency,
        signal_send_time=payload.signal_send_time,
        signal_recipient_emails=json.dumps(payload.signal_recipient_emails),
    )
    db.add(stream)
    db.commit()

    # Wire up the scheduler for the new stream immediately
    from scheduler import reschedule_stream
    reschedule_stream(stream)

    logger.info("Created new stream '%s' (id=%d) under property '%s'", stream.name, stream.id, prop.name)
    return JSONResponse({
        "status": "ok",
        "stream_id": stream.id,
        "name": stream.name,
        "display_name": stream.display_name,
    })


# ---------------------------------------------------------------------------
# Webhook — inbound email
# ---------------------------------------------------------------------------

@app.post("/webhook/inbound", tags=["Webhook"], status_code=status.HTTP_200_OK)
async def inbound_email_webhook(request: Request, db: Session = Depends(get_db)):
    """
    SendGrid inbound email webhook — forwarded-email model.

    Routes incoming emails to the correct stream by matching the recipient
    address to stream.inbound_email.
    """
    try:
        form = await request.form()
        form_data = dict(form)
    except Exception as exc:
        logger.error("Failed to parse inbound webhook form data: %s", exc)
        return JSONResponse({"status": "error", "detail": "form parse failure"})

    debug_fields = {k: v for k, v in form_data.items() if k not in ("text", "html", "headers")}
    logger.info("Inbound webhook raw fields: %s", debug_fields)

    try:
        parsed = parse_inbound_email(form_data)
    except ValueError as exc:
        logger.warning("Could not parse inbound email: %s", exc)
        return JSONResponse({"status": "error", "detail": str(exc)})

    # Deduplicate by message_id
    existing = db.query(Email).filter(Email.message_id == parsed["message_id"]).first()
    if existing:
        logger.info("Duplicate message_id %s — skipping.", parsed["message_id"])
        return JSONResponse({"status": "duplicate"})

    # Route list@ emails (digest request or "done" reply)
    recipient = parsed.get("recipient", "")
    if recipient.startswith("list@"):
        stream = _resolve_stream(db, recipient) or db.query(Stream).first()
        if stream is None:
            return JSONResponse({"status": "error", "detail": "no_stream_configured"})

        sender_email = parsed["sender_email"] or stream.staff_email
        subject = parsed.get("subject", "")

        if re.search(r"^re:", subject.strip(), re.IGNORECASE) and DIGEST_SUBJECT_PREFIX.lower() in subject.lower():
            mark_all, task_ids = parse_done_reply(parsed.get("body", ""))
            now = datetime.now(timezone.utc)
            if mark_all:
                tasks = db.query(CommittedTask).filter(
                    CommittedTask.stream_id == stream.id,
                    CommittedTask.completed == False,
                ).all()
                for t in tasks:
                    t.completed = True
                    t.completed_at = now
                    t.completed_via = "email"
                db.commit()
                logger.info("Marked %d tasks complete via email (done all)", len(tasks))
            elif task_ids:
                tasks = db.query(CommittedTask).filter(
                    CommittedTask.id.in_(task_ids),
                    CommittedTask.stream_id == stream.id,
                ).all()
                for t in tasks:
                    t.completed = True
                    t.completed_at = now
                    t.completed_via = "email"
                db.commit()
                logger.info("Marked tasks %s complete via email", task_ids)
            return JSONResponse({"status": "ok", "action": "tasks_marked_done"})

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        emails_today = (
            db.query(Email)
            .filter(Email.stream_id == stream.id, Email.received_at >= today_start, Email.draft_sent == True)
            .order_by(Email.received_at.desc())
            .all()
        )
        emails_data = [
            {"subject": e.subject or "", "sender_name": e.sender_name or "", "intents": json.loads(e.intent or "[]")}
            for e in emails_today
        ]
        pending_tasks = (
            db.query(CommittedTask)
            .filter(CommittedTask.stream_id == stream.id, CommittedTask.completed == False)
            .order_by(CommittedTask.id.asc())
            .all()
        )
        tasks_data = [
            {"id": t.id, "task_text": t.task_text, "guest_name": t.guest_name or "", "email_subject": t.email_subject or ""}
            for t in pending_tasks
        ]
        date_label = datetime.now(timezone.utc).strftime("%A, %B %-d, %Y")
        send_digest(
            recipient_email=sender_email,
            hotel_name=stream.display_name,
            emails_today=emails_data,
            pending_tasks=tasks_data,
            date_label=date_label,
        )
        logger.info("Digest sent to %s | emails=%d | pending_tasks=%d", sender_email, len(emails_data), len(tasks_data))
        return JSONResponse({"status": "ok", "action": "digest_sent"})

    # Resolve stream by recipient email
    stream = _resolve_stream(db, parsed.get("recipient", ""))
    if stream is None:
        stream = db.query(Stream).first()
        if stream is None:
            logger.error("No streams configured. Cannot process email.")
            return JSONResponse({"status": "error", "detail": "no_stream_configured"})

    # Send draft replies back to whoever forwarded the email.
    # parsed["sender_email"] is the From header — the person who forwarded to
    # the concierge inbox.  Fall back to stream.staff_email only if missing.
    forwarder_email = parsed["sender_email"] or stream.staff_email
    forwarder_name = parsed["sender_name"] or "Staff"
    logger.info("Draft replies will be sent to forwarder: %s", forwarder_email)

    fwd = parsed.get("forwarded")
    if fwd:
        original_sender_name = fwd["original_sender_name"]
        original_sender_email = fwd["original_sender_email"]
        original_subject = fwd["original_subject"] or parsed["subject"]
        original_body = fwd["original_body"]
        is_forwarded = True
        logger.info("Processing forwarded email | forwarder=%s | original_sender=%s", forwarder_email, original_sender_email)
    else:
        original_sender_name = parsed["sender_name"]
        original_sender_email = parsed["sender_email"]
        original_subject = parsed["subject"]
        original_body = parsed["body"]
        is_forwarded = False

    email_record = Email(
        stream_id=stream.id,
        property_id=stream.id,   # legacy compat
        message_id=parsed["message_id"],
        sender_name=original_sender_name,
        sender_email=original_sender_email,
        subject=original_subject,
        body=original_body,
        received_at=parsed["received_at"],
    )
    db.add(email_record)
    db.flush()

    pipeline_start = time.monotonic()

    intents = classify_intent(original_subject, original_body)
    email_record.intent = json.dumps(intents)
    email_record.processed = True

    # --- Guest memory lookup ------------------------------------------------
    guest_ctx: str | None = None
    try:
        history = lookup_guest_history(db, original_sender_email, stream_id=stream.id)
        if history:
            guest_ctx = build_guest_context(history)
            logger.info(
                "Guest memory: %d prior interactions found for %s",
                len(history), original_sender_email,
            )
    except Exception as exc:
        logger.warning("Guest memory lookup failed (non-fatal): %s", exc)

    knowledge_ctx: str | None = None
    try:
        rag_query = f"{original_subject} {original_body[:300]}"
        knowledge_ctx = get_relevant_context(db, stream.id, rag_query) or None
        if knowledge_ctx:
            logger.info("RAG context retrieved for email %s (%d chars)", parsed["message_id"], len(knowledge_ctx))
    except Exception as exc:
        logger.warning("RAG retrieval failed (non-fatal): %s", exc)

    draft_text = None
    try:
        forwarder_context = (
            f"Forwarded by {forwarder_name} ({forwarder_email}) for review." if is_forwarded else None
        )
        draft_text = generate_draft(
            sender_name=original_sender_name,
            subject=original_subject,
            body=original_body,
            intents=intents,
            hotel_name=stream.display_name,
            forwarder_context=forwarder_context,
            knowledge_context=knowledge_ctx,
            guest_context=guest_ctx,
        )
    except Exception as exc:
        logger.error("Draft generation failed for email %s: %s", parsed["message_id"], exc)

    guardrail = None
    if draft_text:
        try:
            guardrail = run_guardrails(
                draft=draft_text,
                subject=original_subject,
                body=original_body,
                intents=intents,
                hotel_name=stream.display_name,
                knowledge_context=knowledge_ctx,
            )
        except Exception as exc:
            logger.warning("Guardrail evaluation failed (non-fatal): %s", exc)

    sent = False
    draft_record = None
    feedback_token = _generate_feedback_token()
    if draft_text:
        processing_ms = int((time.monotonic() - pipeline_start) * 1000)

        # Create the DraftReply record first so we have an ID for the send button
        draft_record = DraftReply(
            email_id=email_record.id,
            draft_text=draft_text,
            feedback_token=feedback_token,
            needs_review=bool(guardrail and not guardrail.safe_to_send),
            review_reason=guardrail.review_reason if guardrail else None,
            guardrail_confidence=guardrail.confidence if guardrail else None,
            guardrail_flags=json.dumps(guardrail.flags) if guardrail else "[]",
            processing_ms=processing_ms,
        )
        db.add(draft_record)
        db.flush()  # assigns draft_record.id without committing

        if guardrail is None or guardrail.safe_to_send:
            sent = send_draft_to_staff(
                staff_email=forwarder_email,
                guest_name=original_sender_name,
                guest_email=original_sender_email,
                original_subject=original_subject,
                draft_text=draft_text,
                hotel_name=stream.display_name,
                intents=intents,
                feedback_token=feedback_token,
                draft_id=draft_record.id,
            )
        else:
            logger.info("Draft held for human review | reason=%s", guardrail.review_reason)

        email_record.draft_sent = sent
        draft_record.sent_at = datetime.now(timezone.utc) if sent else None
        draft_record.feedback_token = feedback_token if sent else None

    if draft_text:
        try:
            task_strings = extract_tasks(draft_text, guest_name=original_sender_name)
            for task_str in task_strings:
                task = CommittedTask(
                    stream_id=stream.id,
                    property_id=stream.id,   # legacy compat
                    email_id=email_record.id,
                    draft_reply_id=draft_record.id if draft_record else None,
                    task_text=task_str,
                    guest_name=original_sender_name,
                    guest_email=original_sender_email,
                    email_subject=original_subject,
                    task_date=datetime.now(timezone.utc),
                )
                db.add(task)
            if task_strings:
                logger.info("Extracted %d tasks from draft for email_id=%d", len(task_strings), email_record.id)
        except Exception as exc:
            logger.warning("Task extraction failed (non-fatal): %s", exc)

    # --- Record guest interaction for memory --------------------------------
    if original_sender_email and draft_text:
        try:
            record_interaction(
                db=db,
                stream_id=stream.id,
                guest_email=original_sender_email,
                guest_name=original_sender_name,
                subject=original_subject,
                intents=intents,
                draft_text=draft_text,
                body=original_body,
            )
        except Exception as exc:
            logger.warning("Guest interaction recording failed (non-fatal): %s", exc)

    db.commit()
    logger.info(
        "Webhook processed | email_id=%d | stream=%s | forwarded=%s | forwarder=%s | "
        "original_sender=%s | intents=%s | draft_sent=%s | needs_review=%s",
        email_record.id, stream.name, is_forwarded, forwarder_email,
        original_sender_email, intents, sent,
        bool(guardrail and not guardrail.safe_to_send),
    )

    return JSONResponse({
        "status": "ok",
        "email_id": email_record.id,
        "stream_id": stream.id,
        "stream_name": stream.name,
        "forwarded": is_forwarded,
        "forwarder": forwarder_email,
        "original_sender": original_sender_email,
        "intents": intents,
        "draft_sent": sent,
        "needs_review": bool(guardrail and not guardrail.safe_to_send),
        "processing_ms": draft_record.processing_ms if draft_record else None,
        "guardrail": {
            "safe_to_send": guardrail.safe_to_send,
            "confidence": guardrail.confidence,
            "flags": guardrail.flags,
            "review_reason": guardrail.review_reason,
        } if guardrail else None,
    })


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

@app.post("/signal/trigger", tags=["Signal"])
async def trigger_signal(payload: SignalTriggerRequest, db: Session = Depends(get_db)):
    """Manually trigger signal generation for a stream."""
    stream = db.query(Stream).filter(Stream.id == payload.stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream {payload.stream_id} not found.")

    briefing = await run_signal_for_stream(stream_id=payload.stream_id, hours_back=payload.hours_back)

    if briefing is None:
        return JSONResponse(status_code=200, content={"status": "no_data", "message": "No emails in the time window."})

    return JSONResponse({
        "status": "ok",
        "stream_id": payload.stream_id,
        "stream_name": stream.name,
        "display_name": stream.display_name,
        "briefing": briefing,
    })


# ---------------------------------------------------------------------------
# GM Weekly Digest
# ---------------------------------------------------------------------------

class GMDigestRequest(BaseModel):
    stream_id: int
    days_back: int = 7


@app.post("/api/gm-digest/trigger", tags=["GM Digest"])
async def trigger_gm_digest(payload: GMDigestRequest, db: Session = Depends(get_db)):
    """Manually trigger the weekly GM intelligence digest for a stream."""
    stream = db.query(Stream).filter(Stream.id == payload.stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream {payload.stream_id} not found.")

    digest = await run_weekly_gm_digest(stream_id=payload.stream_id)

    if digest is None:
        return JSONResponse(
            status_code=200,
            content={"status": "no_data", "message": "No emails in the time window."},
        )

    return JSONResponse({
        "status": "ok",
        "stream_id": payload.stream_id,
        "stream_name": stream.name,
        "display_name": stream.display_name,
        "digest": digest,
    })


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

@app.post("/api/knowledge/{stream_id}/upload", tags=["Knowledge"])
async def upload_knowledge_document(
    stream_id: int,
    file: UploadFile = File(None),
    title: str = Form(None),
    content: str = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a knowledge document for a stream."""
    stream = db.query(Stream).filter(Stream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found.")

    if file and file.filename:
        raw = await file.read()
        try:
            doc_content = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded plain text.")
        filename = file.filename
    elif content:
        doc_content = content
        count = db.query(KnowledgeDocument).filter_by(stream_id=stream_id).count()
        filename = f"document_{stream_id}_{count + 1}.txt"
    else:
        raise HTTPException(status_code=400, detail="Provide either a file upload or a 'content' field.")

    if not doc_content.strip():
        raise HTTPException(status_code=400, detail="Document content is empty.")

    doc = ingest_document(db, stream_id, filename, doc_content, title)

    return JSONResponse({
        "status": "ok",
        "id": doc.id,
        "title": doc.title,
        "filename": doc.filename,
        "word_count": len(doc_content.split()),
        "chunk_count": doc.chunk_count,
    })


@app.get("/api/knowledge/{stream_id}", tags=["Knowledge"])
async def list_knowledge_documents(stream_id: int, db: Session = Depends(get_db)):
    """List all knowledge documents for a stream."""
    stream = db.query(Stream).filter(Stream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found.")

    docs = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.stream_id == stream_id)
        .order_by(KnowledgeDocument.uploaded_at.desc())
        .all()
    )
    return JSONResponse({
        "stream_id": stream_id,
        "stream_name": stream.name,
        "hotel_name": stream.display_name,
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "title": d.title,
                "chunk_count": d.chunk_count,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            }
            for d in docs
        ],
    })


@app.delete("/api/knowledge/{stream_id}/{doc_id}", tags=["Knowledge"])
async def delete_knowledge_document(stream_id: int, doc_id: int, db: Session = Depends(get_db)):
    """Delete a knowledge document."""
    doc = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == doc_id, KnowledgeDocument.stream_id == stream_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    db.delete(doc)
    db.commit()
    logger.info("Deleted knowledge doc id=%d ('%s') from stream %d", doc_id, doc.title, stream_id)
    return JSONResponse({"status": "ok", "deleted_id": doc_id})


@app.post("/api/knowledge/{stream_id}/search", tags=["Knowledge"])
async def search_knowledge_documents(stream_id: int, query: str = Form(...), db: Session = Depends(get_db)):
    """Test knowledge retrieval for a stream."""
    stream = db.query(Stream).filter(Stream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found.")
    context = get_relevant_context(db, stream_id, query)
    return JSONResponse({
        "query": query,
        "context_length": len(context),
        "context": context or "(no relevant documents found)",
    })


# ---------------------------------------------------------------------------
# Email history
# ---------------------------------------------------------------------------

@app.get("/api/emails/{stream_id}", tags=["Emails"])
async def list_emails(stream_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """Return recent emails for a stream, newest first."""
    stream = db.query(Stream).filter(Stream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found.")

    emails = (
        db.query(Email)
        .filter(Email.stream_id == stream_id)
        .order_by(Email.received_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )

    items = []
    for email in emails:
        draft = (
            db.query(DraftReply)
            .filter(DraftReply.email_id == email.id)
            .order_by(DraftReply.id.desc())
            .first()
        )
        items.append({
            "id": email.id,
            "sender_name": email.sender_name,
            "sender_email": email.sender_email,
            "subject": email.subject,
            "body": email.body,
            "received_at": email.received_at.isoformat() if email.received_at else None,
            "intents": json.loads(email.intent) if email.intent else [],
            "draft_sent": email.draft_sent,
            "draft_text": draft.draft_text if draft else None,
            "needs_review": draft.needs_review if draft else False,
            "guardrail_confidence": draft.guardrail_confidence if draft else None,
            "guardrail_flags": json.loads(draft.guardrail_flags or "[]") if draft else [],
            "review_reason": draft.review_reason if draft else None,
            "reviewer_action": draft.reviewer_action if draft else None,
            "processing_ms": draft.processing_ms if draft else None,
        })

    return JSONResponse({
        "stream_id": stream_id,
        "stream_name": stream.name,
        "hotel_name": stream.display_name,
        "total": len(items),
        "emails": items,
    })


# ---------------------------------------------------------------------------
# Review Queue
# ---------------------------------------------------------------------------

@app.get("/api/review/{stream_id}", tags=["Review Queue"])
async def list_review_queue(stream_id: int, db: Session = Depends(get_db)):
    """List draft replies held for human review in a stream."""
    stream = db.query(Stream).filter(Stream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found.")

    pending_drafts = (
        db.query(DraftReply)
        .join(Email, DraftReply.email_id == Email.id)
        .filter(
            Email.stream_id == stream_id,
            DraftReply.needs_review == True,
            DraftReply.reviewer_action == None,
        )
        .order_by(DraftReply.id.desc())
        .all()
    )

    items = []
    for draft in pending_drafts:
        email = db.query(Email).filter(Email.id == draft.email_id).first()
        items.append({
            "draft_id": draft.id,
            "email_id": draft.email_id,
            "sender_name": email.sender_name if email else None,
            "sender_email": email.sender_email if email else None,
            "subject": email.subject if email else None,
            "intents": email.intents if email else [],
            "draft_text": draft.draft_text,
            "guardrail_confidence": draft.guardrail_confidence,
            "guardrail_flags": json.loads(draft.guardrail_flags or "[]"),
            "review_reason": draft.review_reason,
            "created_at": email.received_at.isoformat() if email and email.received_at else None,
        })

    return JSONResponse({
        "stream_id": stream_id,
        "stream_name": stream.name,
        "hotel_name": stream.display_name,
        "pending_count": len(items),
        "items": items,
    })


@app.post("/api/review/{draft_id}/approve", tags=["Review Queue"])
async def approve_draft(draft_id: int, db: Session = Depends(get_db)):
    """Approve a held draft — sends it and marks it reviewed."""
    draft = db.query(DraftReply).filter(DraftReply.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if not draft.needs_review:
        raise HTTPException(status_code=400, detail="This draft was not held for review.")
    if draft.reviewer_action is not None:
        raise HTTPException(status_code=409, detail=f"Draft already actioned: {draft.reviewer_action}")

    email = db.query(Email).filter(Email.id == draft.email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Associated email not found.")

    stream = db.query(Stream).filter(Stream.id == email.stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found.")

    sent = send_draft_to_staff(
        staff_email=stream.staff_email,
        guest_name=email.sender_name,
        guest_email=email.sender_email,
        original_subject=email.subject,
        draft_text=draft.draft_text,
        hotel_name=stream.display_name,
        intents=email.intents,
    )

    draft.reviewer_action = "approved"
    draft.reviewed_at = datetime.now(timezone.utc)
    if sent:
        draft.sent_at = datetime.now(timezone.utc)
        email.draft_sent = True

    db.commit()
    logger.info("Review queue: draft_id=%d approved | sent=%s", draft_id, sent)
    return JSONResponse({"status": "ok", "draft_id": draft_id, "reviewer_action": "approved", "sent": sent})


@app.post("/api/review/{draft_id}/reject", tags=["Review Queue"])
async def reject_draft(draft_id: int, db: Session = Depends(get_db)):
    """Reject a held draft — marks it reviewed without sending."""
    draft = db.query(DraftReply).filter(DraftReply.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if not draft.needs_review:
        raise HTTPException(status_code=400, detail="This draft was not held for review.")
    if draft.reviewer_action is not None:
        raise HTTPException(status_code=409, detail=f"Draft already actioned: {draft.reviewer_action}")

    draft.reviewer_action = "rejected"
    draft.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("Review queue: draft_id=%d rejected", draft_id)
    return JSONResponse({"status": "ok", "draft_id": draft_id, "reviewer_action": "rejected"})


# ---------------------------------------------------------------------------
# On-demand draft generation
# ---------------------------------------------------------------------------

@app.post("/api/emails/{email_id}/draft", tags=["Review Queue"])
async def generate_email_draft(email_id: int, db: Session = Depends(get_db)):
    """Generate (or re-generate) an AI draft reply for a specific email."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found.")

    stream = db.query(Stream).filter(Stream.id == email.stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found.")

    knowledge_ctx: str | None = None
    try:
        rag_query = f"{email.subject} {(email.body or '')[:300]}"
        knowledge_ctx = get_relevant_context(db, stream.id, rag_query) or None
    except Exception as exc:
        logger.warning("RAG retrieval failed (non-fatal): %s", exc)

    try:
        draft_text = generate_draft(
            sender_name=email.sender_name,
            subject=email.subject,
            body=email.body,
            intents=email.intents,
            hotel_name=stream.display_name,
            forwarder_context=None,
            knowledge_context=knowledge_ctx,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Draft generation failed: {exc}")

    draft_record = DraftReply(
        email_id=email.id,
        draft_text=draft_text,
        needs_review=True,
        review_reason="Manually generated via dashboard",
        guardrail_confidence="medium",
        guardrail_flags="[]",
    )
    db.add(draft_record)
    db.commit()
    logger.info("Generated on-demand draft | email_id=%d | draft_id=%d", email_id, draft_record.id)

    return JSONResponse({
        "status": "ok",
        "email_id": email_id,
        "draft_id": draft_record.id,
        "draft_text": draft_text,
    })


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@app.get("/api/tasks/{stream_id}", tags=["Tasks"])
async def list_tasks(stream_id: int, pending_only: bool = False, db: Session = Depends(get_db)):
    """Return committed tasks for a stream. Pass ?pending_only=true for incomplete only."""
    stream = db.query(Stream).filter(Stream.id == stream_id).first()
    if not stream:
        raise HTTPException(status_code=404, detail=f"Stream {stream_id} not found.")

    query = db.query(CommittedTask).filter(CommittedTask.stream_id == stream_id)
    if pending_only:
        query = query.filter(CommittedTask.completed == False)

    tasks = query.order_by(CommittedTask.id.desc()).all()

    return JSONResponse({
        "stream_id": stream_id,
        "stream_name": stream.name,
        "property_id": stream.property_id,
        "hotel_name": stream.display_name,
        "total": len(tasks),
        "pending": sum(1 for t in tasks if not t.completed),
        "tasks": [
            {
                "id": t.id,
                "task_text": t.task_text,
                "guest_name": t.guest_name,
                "guest_email": t.guest_email,
                "email_subject": t.email_subject,
                "email_id": t.email_id,
                "completed": t.completed,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "completed_via": t.completed_via,
                "task_date": t.task_date.isoformat() if t.task_date else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
    })


@app.patch("/api/tasks/{task_id}", tags=["Tasks"])
async def update_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark a task as complete or incomplete. Body: { "completed": true|false }"""
    body = await request.json()
    completed = body.get("completed")
    if completed is None:
        raise HTTPException(status_code=400, detail="Body must include 'completed' boolean.")

    task = db.query(CommittedTask).filter(CommittedTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    task.completed = bool(completed)
    task.completed_at = datetime.now(timezone.utc) if completed else None
    task.completed_via = "dashboard" if completed else None
    db.commit()

    logger.info("Task %d marked %s via dashboard", task_id, "complete" if completed else "incomplete")
    return JSONResponse({
        "status": "ok",
        "task_id": task_id,
        "completed": task.completed,
        "completed_via": task.completed_via,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_stream(db: Session, recipient_email: str) -> Stream | None:
    """Find a stream by its configured inbound_email address."""
    if not recipient_email:
        return None
    return (
        db.query(Stream)
        .filter(Stream.inbound_email == recipient_email.lower().strip())
        .first()
    )
