"""
database.py — SQLAlchemy models and database initialization.
Uses SQLite for the MVP; swap DATABASE_URL to swap backends.

Architecture: Company → Property → Stream → (emails, tasks, signals, knowledge)
  - Company:  top-level tenant (a brand, hospital, etc.)
  - Property: a physical location (e.g. "Park Hyatt Aviara")
  - Stream:   an operational department/channel (e.g. "Concierge", "Spa")
              Each stream has its own inbox, knowledge base, task list, and signals.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Railway provisions Postgres with a postgres:// URL; SQLAlchemy 2.x requires postgresql://
_db_url = settings.database_url
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    _db_url,
    connect_args={"check_same_thread": False} if "sqlite" in _db_url else {},
    echo=False,
)

# Enable WAL mode for SQLite to support concurrent reads
if "sqlite" in _db_url:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Company — the top-level tenant (a hotel brand, hospital department, etc.)
# Everything in the system belongs to a Company.
# ---------------------------------------------------------------------------

class Company(Base):
    """A company / organization that subscribes to Ready Concierge."""

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)            # e.g. "Park Hyatt"
    slug = Column(String(100), unique=True, nullable=False, index=True)  # e.g. "park-hyatt"
    domain = Column(String(255), nullable=True)           # e.g. "parkhyatt.com" (optional, for future SSO)
    plan = Column(String(50), default="trial")            # trial | starter | pro | enterprise
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    properties = relationship("Property", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company id={self.id} name={self.name!r} slug={self.slug!r}>"


# ---------------------------------------------------------------------------
# Property — a physical location / hotel within a Company.
# Groups one or more Streams (departments) under a single address.
# ---------------------------------------------------------------------------

class Property(Base):
    """A hotel property (or location) grouping multiple streams."""

    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)             # e.g. "Park Hyatt Aviara"
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="properties")
    streams = relationship("Stream", back_populates="parent_property", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Property id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# Stream — an operational channel / department within a Property.
# Each stream has its own inbox, staff contacts, signal config, knowledge
# base, task list, and email history.
# Examples: Concierge, Spa, Restaurant Events
# ---------------------------------------------------------------------------

class Stream(Base):
    """An operational channel (department) within a property."""

    __tablename__ = "streams"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # denormalized
    name = Column(String(100), nullable=False)            # e.g. "Concierge"
    display_name = Column(String(255), nullable=False)    # e.g. "Park Hyatt Aviara — Concierge"
    inbound_email = Column(String(255), unique=True)      # e.g. concierge@aviara.preshift.app
    staff_email = Column(String(255), nullable=False)     # where draft replies are sent
    signal_enabled = Column(Boolean, default=True)
    signal_frequency = Column(String(50), default="daily")   # "daily" | "hourly"
    signal_send_time = Column(String(10), default="06:00")   # HH:MM (for daily)
    signal_recipient_emails = Column(Text, default="[]")     # JSON array of strings
    created_at = Column(DateTime, default=datetime.utcnow)

    parent_property = relationship("Property", back_populates="streams")
    emails = relationship("Email", back_populates="stream", cascade="all, delete-orphan")
    signal_snapshots = relationship("SignalSnapshot", back_populates="stream", cascade="all, delete-orphan")
    knowledge_documents = relationship("KnowledgeDocument", back_populates="stream", cascade="all, delete-orphan")
    committed_tasks = relationship("CommittedTask", back_populates="stream", cascade="all, delete-orphan")

    @property
    def signal_recipients(self) -> list[str]:
        try:
            return json.loads(self.signal_recipient_emails or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def hotel_name(self) -> str:
        """Backward-compat alias — returns the stream's display name."""
        return self.display_name

    def __repr__(self) -> str:
        return f"<Stream id={self.id} name={self.name!r} display={self.display_name!r}>"


# ---------------------------------------------------------------------------
# KnowledgeDocument — uploaded docs (concierge guides, FAQs, policies, etc.)
# These are chunked and embedded for RAG responses.
# ---------------------------------------------------------------------------

class KnowledgeDocument(Base):
    """An uploaded knowledge document for a stream (used for RAG)."""

    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    stream_id = Column(Integer, ForeignKey("streams.id"), nullable=True, index=True)
    property_id = Column(Integer, nullable=True)          # legacy — migration compat
    filename = Column(String(512), nullable=False)
    title = Column(String(512), nullable=True)            # human-readable title
    content = Column(Text, nullable=False)                # full raw text
    chunk_count = Column(Integer, default=0)              # how many vector chunks were created
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    stream = relationship("Stream", back_populates="knowledge_documents")

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} filename={self.filename!r}>"


# ---------------------------------------------------------------------------
# Email — an inbound guest email received via the SendGrid webhook
# ---------------------------------------------------------------------------

class Email(Base):
    """An inbound guest email received via the SendGrid webhook."""

    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    stream_id = Column(Integer, ForeignKey("streams.id"), nullable=True, index=True)
    property_id = Column(Integer, nullable=True)          # legacy — migration compat
    message_id = Column(String(512), unique=True, index=True)
    sender_name = Column(String(255))
    sender_email = Column(String(255), index=True)
    subject = Column(Text)
    body = Column(Text)
    received_at = Column(DateTime, default=datetime.utcnow)
    intent = Column(Text, default="[]")      # JSON array of intent strings
    processed = Column(Boolean, default=False)
    draft_sent = Column(Boolean, default=False)

    stream = relationship("Stream", back_populates="emails")
    draft_replies = relationship("DraftReply", back_populates="email", cascade="all, delete-orphan")

    @property
    def intents(self) -> list[str]:
        try:
            return json.loads(self.intent or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def __repr__(self) -> str:
        return f"<Email id={self.id} from={self.sender_email!r} subject={self.subject!r}>"


# ---------------------------------------------------------------------------
# DraftReply — an AI-generated draft reply for a guest email
# ---------------------------------------------------------------------------

class DraftReply(Base):
    """An AI-generated draft reply for a guest email."""

    __tablename__ = "draft_replies"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False)
    draft_text = Column(Text, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    accepted = Column(Boolean, nullable=True)   # null = no feedback yet; True/False = staff verdict
    sources_used = Column(Text, default="[]")   # JSON array of KnowledgeDocument ids used in RAG

    # Guardrail / review-queue fields
    needs_review = Column(Boolean, default=False)             # held for human review
    review_reason = Column(Text, nullable=True)               # why it was held
    guardrail_confidence = Column(String(20), nullable=True)  # high | medium | low
    guardrail_flags = Column(Text, default="[]")              # JSON array of flag strings
    reviewed_at = Column(DateTime, nullable=True)             # when a human actioned it
    reviewer_action = Column(String(20), nullable=True)       # "approved" | "rejected"
    feedback_token = Column(String(64), nullable=True, unique=True, index=True)  # for one-click feedback links
    processing_ms = Column(Integer, nullable=True)  # pipeline processing time in milliseconds

    email = relationship("Email", back_populates="draft_replies")

    def __repr__(self) -> str:
        return f"<DraftReply id={self.id} email_id={self.email_id}>"


# ---------------------------------------------------------------------------
# CommittedTask — action items / commitments extracted from AI draft replies
# ---------------------------------------------------------------------------

class CommittedTask(Base):
    """An action item / commitment extracted from an AI-generated draft reply."""

    __tablename__ = "committed_tasks"

    id = Column(Integer, primary_key=True, index=True)
    stream_id = Column(Integer, ForeignKey("streams.id"), nullable=True, index=True)
    property_id = Column(Integer, nullable=True)          # legacy — migration compat
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=True)
    draft_reply_id = Column(Integer, ForeignKey("draft_replies.id"), nullable=True)
    task_text = Column(Text, nullable=False)                               # e.g. "Book golf tee time at 10am Friday"
    guest_name = Column(String(255), nullable=True)                        # who the task relates to
    guest_email = Column(String(255), nullable=True)
    email_subject = Column(Text, nullable=True)                            # for context in the digest
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
    completed_via = Column(String(20), nullable=True)                      # "dashboard" | "email"
    task_date = Column(DateTime, nullable=False)                           # date of creation (for daily filtering)
    created_at = Column(DateTime, default=datetime.utcnow)

    stream = relationship("Stream", back_populates="committed_tasks")

    def __repr__(self) -> str:
        return f"<CommittedTask id={self.id} text={repr(self.task_text)[:40]} completed={self.completed}>"


# ---------------------------------------------------------------------------
# SignalSnapshot / SignalPattern / SignalFlag — periodic intelligence briefings
# ---------------------------------------------------------------------------

class GuestInteraction(Base):
    """
    A record of every interaction with a guest, used for guest memory.

    When a guest emails again, the system looks up their history and
    injects a summary into the draft prompt so the reply can reference
    prior stays, preferences, and conversations.
    """

    __tablename__ = "guest_interactions"

    id = Column(Integer, primary_key=True, index=True)
    stream_id = Column(Integer, ForeignKey("streams.id"), nullable=True, index=True)
    guest_email = Column(String(255), nullable=False, index=True)
    guest_name = Column(String(255), nullable=True)
    subject = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)         # AI-generated one-line summary of the interaction
    intents = Column(Text, default="[]")           # JSON array of intent strings
    draft_text = Column(Text, nullable=True)       # the draft that was generated (for context)
    feedback = Column(String(20), nullable=True)   # "perfect" | "changed" | null
    interaction_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<GuestInteraction id={self.id} guest={self.guest_email!r} at={self.interaction_at}>"


class DraftFeedback(Base):
    """
    One-click feedback captured from the draft email.

    Staff click "This was perfect" or "This needed changes" in the email.
    No login required — the link contains a signed token.
    """

    __tablename__ = "draft_feedback"

    id = Column(Integer, primary_key=True, index=True)
    draft_reply_id = Column(Integer, ForeignKey("draft_replies.id"), nullable=False, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=True)
    stream_id = Column(Integer, ForeignKey("streams.id"), nullable=True)
    verdict = Column(String(20), nullable=False)   # "perfect" | "changed"
    clicked_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<DraftFeedback id={self.id} draft={self.draft_reply_id} verdict={self.verdict!r}>"


class SignalSnapshot(Base):
    """A point-in-time signal briefing for a stream."""

    __tablename__ = "signal_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    stream_id = Column(Integer, ForeignKey("streams.id"), nullable=True, index=True)
    property_id = Column(Integer, nullable=True)          # legacy — migration compat
    time_window_start = Column(DateTime, nullable=False)
    time_window_end = Column(DateTime, nullable=False)
    total_emails = Column(Integer, default=0)
    system_state = Column(Text)
    generated_summary = Column(Text, default="{}")  # full JSON blob
    confidence = Column(String(20))                  # high | medium | low
    created_at = Column(DateTime, default=datetime.utcnow)

    stream = relationship("Stream", back_populates="signal_snapshots")
    patterns = relationship("SignalPattern", back_populates="snapshot", cascade="all, delete-orphan")
    flags = relationship("SignalFlag", back_populates="snapshot", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<SignalSnapshot id={self.id} stream_id={self.stream_id}>"


class SignalPattern(Base):
    """A detected pattern within a signal snapshot."""

    __tablename__ = "signal_patterns"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("signal_snapshots.id"), nullable=False)
    pattern_type = Column(String(50))   # spike | cluster | sentiment | multi_signal
    category = Column(String(100))
    count = Column(Integer, default=0)
    description = Column(Text)

    snapshot = relationship("SignalSnapshot", back_populates="patterns")

    def __repr__(self) -> str:
        return f"<SignalPattern id={self.id} type={self.pattern_type} category={self.category}>"


class SignalFlag(Base):
    """A guest-level flag raised in a signal snapshot."""

    __tablename__ = "signal_flags"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("signal_snapshots.id"), nullable=False)
    guest_name = Column(String(255))
    guest_email = Column(String(255))
    reason = Column(Text)
    priority = Column(String(20), default="normal")  # high | normal | low

    snapshot = relationship("SignalSnapshot", back_populates="flags")

    def __repr__(self) -> str:
        return f"<SignalFlag id={self.id} guest={self.guest_email!r} priority={self.priority}>"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    """FastAPI dependency: yields a database session and closes it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _run_migrations() -> None:
    """
    Apply additive schema migrations for columns / tables added after initial deploy.

    Key migration: renames old `properties` table (the stream-level operational
    unit from the original single-tier architecture) to `streams`, then creates
    a new lightweight `properties` table as a pure grouping layer.
    """
    with engine.connect() as conn:
        if "postgresql" in _db_url:
            from sqlalchemy import text

            # ----------------------------------------------------------------
            # PHASE A: Rename old properties → streams (if not already done).
            # The old `properties` table is identified by having an
            # `inbound_email` column, which the new lightweight table does not.
            # ----------------------------------------------------------------
            has_old_properties = conn.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'properties' AND column_name = 'inbound_email'
            """)).fetchone()

            streams_exists = conn.execute(text("""
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'streams'
            """)).fetchone()

            if has_old_properties and not streams_exists:
                logger.info("Migrating schema: renaming properties → streams...")
                conn.execute(text("ALTER TABLE properties RENAME TO streams"))
                conn.execute(text(
                    "ALTER TABLE streams RENAME COLUMN hotel_name TO display_name"
                ))
                conn.execute(text(
                    "ALTER TABLE streams ADD COLUMN IF NOT EXISTS name VARCHAR(100)"
                ))
                conn.execute(text(
                    "UPDATE streams SET name = 'Concierge' WHERE name IS NULL"
                ))
                conn.commit()
                logger.info("Schema migration: properties → streams complete.")

            # ----------------------------------------------------------------
            # PHASE B: Create new lightweight properties grouping table.
            # ----------------------------------------------------------------
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS properties (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id),
                    name VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()

            # ----------------------------------------------------------------
            # PHASE C: Add property_id FK to streams.
            # ----------------------------------------------------------------
            conn.execute(text(
                "ALTER TABLE streams ADD COLUMN IF NOT EXISTS "
                "property_id INTEGER REFERENCES properties(id)"
            ))
            conn.commit()

            # ----------------------------------------------------------------
            # PHASE D: Seed a Property row for each company that has streams
            #          but no property yet; then link streams → property.
            # ----------------------------------------------------------------
            conn.execute(text("""
                INSERT INTO properties (company_id, name, created_at)
                SELECT DISTINCT s.company_id, 'Park Hyatt Aviara', NOW()
                FROM streams s
                WHERE s.company_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM properties p WHERE p.company_id = s.company_id
                  )
                ON CONFLICT DO NOTHING
            """))
            conn.execute(text("""
                UPDATE streams s
                SET property_id = p.id
                FROM properties p
                WHERE p.company_id = s.company_id
                  AND s.property_id IS NULL
            """))
            conn.commit()

            # ----------------------------------------------------------------
            # PHASE E: Add stream_id to child tables + backfill from property_id.
            # ----------------------------------------------------------------
            for tbl in ("emails", "committed_tasks", "signal_snapshots", "knowledge_documents"):
                conn.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS "
                    f"stream_id INTEGER REFERENCES streams(id)"
                ))
            conn.commit()

            for tbl in ("emails", "committed_tasks", "signal_snapshots", "knowledge_documents"):
                conn.execute(text(
                    f"UPDATE {tbl} SET stream_id = property_id "
                    f"WHERE stream_id IS NULL AND property_id IS NOT NULL"
                ))
            conn.commit()

            # ----------------------------------------------------------------
            # PHASE F: Legacy incremental migrations (kept for compat).
            # ----------------------------------------------------------------
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS sources_used TEXT DEFAULT '[]'"
            ))
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE"
            ))
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS review_reason TEXT"
            ))
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS guardrail_confidence VARCHAR(20)"
            ))
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS guardrail_flags TEXT DEFAULT '[]'"
            ))
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP"
            ))
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS reviewer_action VARCHAR(20)"
            ))
            # Guest memory + feedback tables
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS guest_interactions (
                    id SERIAL PRIMARY KEY,
                    stream_id INTEGER REFERENCES streams(id),
                    guest_email VARCHAR(255) NOT NULL,
                    guest_name VARCHAR(255),
                    subject TEXT,
                    summary TEXT,
                    intents TEXT DEFAULT '[]',
                    draft_text TEXT,
                    feedback VARCHAR(20),
                    interaction_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_guest_interactions_email "
                "ON guest_interactions (guest_email)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_guest_interactions_stream_email "
                "ON guest_interactions (stream_id, guest_email)"
            ))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS draft_feedback (
                    id SERIAL PRIMARY KEY,
                    draft_reply_id INTEGER REFERENCES draft_replies(id),
                    email_id INTEGER REFERENCES emails(id),
                    stream_id INTEGER REFERENCES streams(id),
                    verdict VARCHAR(20) NOT NULL,
                    clicked_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS "
                "feedback_token VARCHAR(64) UNIQUE"
            ))
            conn.execute(text(
                "ALTER TABLE draft_replies ADD COLUMN IF NOT EXISTS "
                "processing_ms INTEGER"
            ))
            conn.commit()

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS committed_tasks (
                    id SERIAL PRIMARY KEY,
                    stream_id INTEGER REFERENCES streams(id),
                    property_id INTEGER,
                    email_id INTEGER REFERENCES emails(id),
                    draft_reply_id INTEGER REFERENCES draft_replies(id),
                    task_text TEXT NOT NULL,
                    guest_name VARCHAR(255),
                    guest_email VARCHAR(255),
                    email_subject TEXT,
                    completed BOOLEAN NOT NULL DEFAULT FALSE,
                    completed_at TIMESTAMP,
                    completed_via VARCHAR(20),
                    task_date TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
            logger.info("Migrations applied.")


def init_db() -> None:
    """Create all tables and seed default data if none exist."""
    # Run migrations FIRST (handles renaming properties → streams in existing DBs),
    # then create_all fills any gaps for fresh installs.
    _run_migrations()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")

    with SessionLocal() as db:
        _seed_default_data(db)  # idempotent — safe to run every deploy
        _seed_knowledge_starter(db)  # load starter knowledge base if empty


def _seed_default_data(db: Session) -> None:
    """Ensure default company, property, and stream exist (idempotent — safe on every deploy)."""
    s = get_settings()
    if not s.default_staff_email:
        logger.info("DEFAULT_STAFF_EMAIL not set — skipping seed.")
        return

    # Get or create the default company by slug
    company = db.query(Company).filter_by(slug="default").first()
    if not company:
        company = Company(
            name=s.default_company_name,
            slug="default",
            plan="trial",
            is_active=True,
        )
        db.add(company)
        db.flush()

    # Get or create the default property under this company
    prop = db.query(Property).filter_by(company_id=company.id).first()
    if not prop:
        prop = Property(
            company_id=company.id,
            name=getattr(s, "default_property_name", s.default_hotel_name),
        )
        db.add(prop)
        db.flush()

    # Get or create the default stream (Concierge) by inbound email
    stream = db.query(Stream).filter_by(inbound_email=s.sendgrid_from_email).first()
    if not stream:
        recipients = [r.strip() for r in s.default_signal_recipients.split(",") if r.strip()]
        stream_name = getattr(s, "default_stream_name", "Concierge")
        stream = Stream(
            property_id=prop.id,
            company_id=company.id,
            name=stream_name,
            display_name=f"{prop.name} — {stream_name}",
            inbound_email=s.sendgrid_from_email,
            staff_email=s.default_staff_email,
            signal_enabled=True,
            signal_frequency="daily",
            signal_send_time="06:00",
            signal_recipient_emails=json.dumps(recipients or [s.default_staff_email]),
        )
        db.add(stream)
    else:
        # Backfill missing fields on existing stream
        if stream.property_id is None:
            stream.property_id = prop.id
        if stream.company_id is None:
            stream.company_id = company.id
        if not stream.name:
            stream.name = "Concierge"
        if not stream.display_name:
            stream.display_name = f"{prop.name} — {stream.name}"

    db.commit()
    logger.info(
        "Verified default company '%s', property '%s', stream '%s'",
        company.name, prop.name, stream.name,
    )


def _seed_knowledge_starter(db: Session) -> None:
    """
    Auto-load the knowledge base starter file into the first stream's
    knowledge base — but only if the stream has zero documents.

    This gives pilot properties a working RAG knowledge base from day one
    without any manual upload required.
    """
    from pathlib import Path

    stream = db.query(Stream).first()
    if not stream:
        return

    # Only seed if the stream has no knowledge documents yet
    existing = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.stream_id == stream.id
    ).count()
    if existing > 0:
        return

    # Look for starter files in knowledge_starter/
    starter_dir = Path(__file__).parent / "knowledge_starter"
    if not starter_dir.is_dir():
        return

    seeded = 0
    for txt_file in sorted(starter_dir.glob("*.txt")):
        content = txt_file.read_text(encoding="utf-8").strip()
        if not content:
            continue

        title = txt_file.stem.replace("_", " ").replace("-", " ").title()
        word_count = len(content.split())
        chunk_count = max(1, round(word_count / 200))

        doc = KnowledgeDocument(
            stream_id=stream.id,
            property_id=stream.id,   # legacy compat
            filename=txt_file.name,
            title=title,
            content=content,
            chunk_count=chunk_count,
        )
        db.add(doc)
        seeded += 1
        logger.info(
            "Seeded knowledge doc '%s' (%d words) into stream '%s'",
            title, word_count, stream.name,
        )

    if seeded:
        db.commit()
        logger.info("Knowledge starter: seeded %d document(s) into stream '%s'", seeded, stream.name)
