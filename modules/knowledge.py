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
MAX_CONTEXT_CHARS = 4_000
# Max number of documents returned per search
MAX_DOCS = 5