"""
knowledge.py — Knowledge base management and RAG retrieval.

Documents are stored in the knowledge_documents table and searched using
PostgreSQL full-text search (tsvector / plainto_tsquery).

At MVP scale this is fast, zero-cost, and good enough for hotel concierge
content (amenity guides, FAQs, menus, policies).  When embeddings become
valuable, this module is the right place to swap in pgvector.
"""

import logging
import textwrap
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import KnowledgeDocument, Property

logger = logging.getLogger(__name__)

# Max characters of knowledge context injected into the Claude prompt.
# ~2 000 chars ≈ roughly 500 tokens — affordable on Haiku.
MAX_CONTEXT_CHARS = 2_000
# Max number of documents returned per search
MAX_DOCS = 3


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def ingest_document(
    db: Session,
    stream_id: int,
    filename: str,
    content: str,
    title: Optional[str] = None,
) -> KnowledgeDocument:
    """
    Store a knowledge document for a stream.

    The full text is stored as-is; PostgreSQL tsvector search runs on the
    content column at query time — no pre-processing needed.

    Args:
        db:          Active SQLAlchemy session.
        stream_id:   The stream this document belongs to.
        filename:    Original filename (for display).
        content:     Full plain-text content of the document.
        title:       Human-readable title (defaults to filename stem).

    Returns:
        The newly created KnowledgeDocument row.
    """
    if title is None:
        # Strip extension for a friendlier default title
        title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()

    # Simple word count as a proxy for chunk_count (1 chunk per ~200 words)
    word_count = len(content.split())
    chunk_count = max(1, round(word_count / 200))

    doc = KnowledgeDocument(
        stream_id=stream_id,
        property_id=stream_id,   # legacy compat
        filename=filename,
        title=title,
        content=content,
        chunk_count=chunk_count,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info(
        "Ingested knowledge doc '%s' for stream %d | %d words | id=%d",
        title, stream_id, word_count, doc.id,
    )
    return doc


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def search_knowledge(
    db: Session,
    property_id: int,
    query: str,
    limit: int = MAX_DOCS,
) -> list[KnowledgeDocument]:
    """
    Full-text search over knowledge documents for a given property.

    Uses PostgreSQL plainto_tsquery (handles stemming, stop words, etc.).
    Falls back to returning the most-recent documents if the query is empty
    or yields no results.

    Args:
        db:          Active SQLAlchemy session.
        property_id: Scope the search to this property.
        query:       Free-text search string (typically subject + body snippet).
        limit:       Maximum number of documents to return.

    Returns:
        List of matching KnowledgeDocument objects sorted by relevance.
    """
    if not query or not query.strip():
        return _fallback_docs(db, property_id, limit)

    # PostgreSQL-specific full-text search; gracefully degrades to fallback
    # if the DB is SQLite (local dev).
    try:
        from database import _db_url  # local import to avoid circular
        if "postgresql" not in _db_url:
            return _simple_keyword_search(db, property_id, query, limit)

        sql = text("""
            SELECT id,
                   ts_rank(
                       to_tsvector('english', content),
                       plainto_tsquery('english', :query)
                   ) AS rank
            FROM knowledge_documents
            WHERE property_id = :property_id
              AND to_tsvector('english', content) @@ plainto_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """)
        rows = db.execute(sql, {"query": query, "property_id": property_id, "limit": limit}).fetchall()

        if not rows:
            # No exact FTS match — fall back to most-recent docs
            logger.debug("FTS returned no results for query %r — using fallback", query)
            return _fallback_docs(db, property_id, limit)

        ids = [row.id for row in rows]
        docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(ids)).all()
        # Preserve FTS rank order
        id_order = {id_: idx for idx, id_ in enumerate(ids)}
        docs.sort(key=lambda d: id_order.get(d.id, 99))
        return docs

    except Exception as exc:
        logger.warning("Knowledge search error: %s — using fallback", exc)
        return _fallback_docs(db, property_id, limit)


def get_relevant_context(
    db: Session,
    property_id: int,
    query: str,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> str:
    """
    Build a formatted knowledge-base context block for injection into prompts.

    Returns an empty string if no documents are available.

    Args:
        db:          Active SQLAlchemy session.
        property_id: Scope to this property.
        query:       The search query (email subject + snippet).
        max_chars:   Hard cap on context size sent to the model.

    Returns:
        A formatted string like::

            === KNOWLEDGE BASE ===
            [Amenities Guide]
            Pool hours: 7 am – 10 pm...

            [Dining Policy]
            Reservations required for...
            =====================

        or an empty string if no documents exist for this property.
    """
    docs = search_knowledge(db, property_id, query)
    if not docs:
        return ""

    sections: list[str] = []
    chars_used = 0

    for doc in docs:
        header = f"[{doc.title or doc.filename}]"
        # Truncate individual doc content if it would bust the budget
        remaining = max_chars - chars_used - len(header) - 4
        if remaining <= 0:
            break
        excerpt = textwrap.shorten(doc.content, width=remaining, placeholder="…")
        section = f"{header}\n{excerpt}"
        sections.append(section)
        chars_used += len(section) + 2  # +2 for the blank line separator

    if not sections:
        return ""

    body = "\n\n".join(sections)
    return f"=== KNOWLEDGE BASE ===\n{body}\n====================="


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fallback_docs(db: Session, property_id: int, limit: int) -> list[KnowledgeDocument]:
    """Return the most recently uploaded documents for a property."""
    return (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.property_id == property_id)
        .order_by(KnowledgeDocument.uploaded_at.desc())
        .limit(limit)
        .all()
    )


def _simple_keyword_search(
    db: Session, property_id: int, query: str, limit: int
) -> list[KnowledgeDocument]:
    """
    Case-insensitive keyword fallback for SQLite (local dev only).

    Scores documents by how many query words appear in their content.
    """
    words = [w.lower() for w in query.split() if len(w) > 2]
    all_docs = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.property_id == property_id)
        .all()
    )
    if not words:
        return all_docs[:limit]

    scored = []
    for doc in all_docs:
        content_lower = doc.content.lower()
        score = sum(1 for w in words if w in content_lower)
        scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:limit] if _ > 0] or all_docs[:limit]
