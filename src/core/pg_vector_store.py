"""pgvector backend — stores embeddings in PostgreSQL using the pgvector extension.

Prerequisites:
  1. PostgreSQL with pgvector installed:
       CREATE EXTENSION IF NOT EXISTS vector;
  2. Set in .env:
       VECTOR_BACKEND=pgvector
       PG_VECTOR_URL=postgresql://user:pass@localhost:5432/akp
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import Index, String, Text, delete, func, select, text
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings
from .document_processor import DocumentChunk, ParsedDocument, chunk_document
from .embeddings import embed_query, embed_texts


# ── ORM model ────────────────────────────────────────────────────────────────

class _Base(DeclarativeBase):
    pass


class _Chunk(_Base):
    __tablename__ = "akp_document_chunks"

    chunk_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    collection: Mapped[str] = mapped_column(String(255), nullable=False, index=True, default="default")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # embedding column is added dynamically after pgvector is confirmed available
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


# ── Engine / session factory ──────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _engine():
    if not settings.pg_vector_url:
        raise RuntimeError(
            "PG_VECTOR_URL is not set. Add it to .env:\n"
            "  PG_VECTOR_URL=postgresql://user:pass@localhost:5432/akp"
        )
    try:
        from pgvector.sqlalchemy import Vector  # noqa: F401
    except ImportError as e:
        raise RuntimeError("pgvector package required: pip install pgvector") from e

    engine = create_engine(settings.pg_vector_url, pool_pre_ping=True)
    return engine


@lru_cache(maxsize=1)
def _session_factory():
    return sessionmaker(bind=_engine(), autocommit=False, autoflush=False)


def _get_session() -> Session:
    return _session_factory()()


def init_db():
    """Create table + indexes. Called once at startup."""
    from pgvector.sqlalchemy import Vector

    # Add the vector column dynamically so the dimension is read from config
    if not hasattr(_Chunk, "embedding"):
        _Chunk.embedding = mapped_column(Vector(settings.embedding_dim), nullable=True)

    engine = _engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    _Base.metadata.create_all(bind=engine)

    # HNSW index for fast cosine search (idempotent)
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS akp_chunks_embedding_hnsw "
            "ON akp_document_chunks USING hnsw (embedding vector_cosine_ops)"
        ))
        conn.commit()


# ── Public interface (mirrors chroma_vector_store) ───────────────────────────

@dataclass
class SearchResult:
    chunk_id: str
    doc_id: str
    content: str
    score: float
    metadata: dict


def list_collections() -> list[dict[str, Any]]:
    with _get_session() as db:
        rows = db.execute(
            select(_Chunk.collection, func.count(_Chunk.chunk_id).label("count"))
            .group_by(_Chunk.collection)
        ).all()
        return [{"name": r.collection, "count": r.count} for r in rows]


def add_document(doc: ParsedDocument, collection: str = "default") -> list[str]:
    chunks = chunk_document(doc, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        return []

    from pgvector.sqlalchemy import Vector  # noqa: F401

    embeddings = embed_texts([c.content for c in chunks])

    with _get_session() as db:
        # Upsert: delete existing chunks for this doc+collection, then re-insert
        db.execute(
            delete(_Chunk).where(
                _Chunk.doc_id == doc.doc_id,
                _Chunk.collection == collection,
            )
        )
        for chunk, vector in zip(chunks, embeddings):
            row = _Chunk(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                collection=collection,
                content=chunk.content,
                embedding=vector,
                chunk_metadata={**chunk.metadata, "doc_id": chunk.doc_id, "collection": collection},
            )
            db.add(row)
        db.commit()

    return [c.chunk_id for c in chunks]


def delete_document(doc_id: str, collection: str = "default") -> int:
    with _get_session() as db:
        result = db.execute(
            delete(_Chunk).where(
                _Chunk.doc_id == doc_id,
                _Chunk.collection == collection,
            )
        )
        db.commit()
        return result.rowcount


def search(
    query: str,
    collection: str = "default",
    top_k: int | None = None,
    where: dict | None = None,
) -> list[SearchResult]:
    k = top_k or settings.default_top_k
    vector = embed_query(query)

    # Build cosine distance expression
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import cast, literal

    vec_literal = cast(literal(json.dumps(vector)), Vector(settings.embedding_dim))
    distance_expr = _Chunk.embedding.op("<=>")(vec_literal)

    with _get_session() as db:
        stmt = (
            select(_Chunk, (1 - distance_expr).label("score"))
            .where(_Chunk.collection == collection)
            .order_by(distance_expr)
            .limit(k)
        )
        # Metadata filter (simple key=value only)
        if where:
            for key, val in where.items():
                stmt = stmt.where(_Chunk.chunk_metadata[key].astext == str(val))

        rows = db.execute(stmt).all()

    return [
        SearchResult(
            chunk_id=row._Chunk.chunk_id,
            doc_id=row._Chunk.doc_id,
            content=row._Chunk.content,
            score=round(float(row.score), 4),
            metadata=row._Chunk.chunk_metadata,
        )
        for row in rows
    ]


def get_document_chunks(doc_id: str, collection: str = "default") -> list[dict]:
    with _get_session() as db:
        rows = db.execute(
            select(_Chunk).where(
                _Chunk.doc_id == doc_id,
                _Chunk.collection == collection,
            ).order_by(_Chunk.chunk_metadata["chunk_index"].as_integer())
        ).scalars().all()
        return [
            {"chunk_id": r.chunk_id, "content": r.content, "metadata": r.chunk_metadata}
            for r in rows
        ]


def list_documents_in_collection(collection: str) -> list[dict]:
    """Return deduplicated document summaries for a collection."""
    with _get_session() as db:
        rows = db.execute(
            select(_Chunk).where(_Chunk.collection == collection)
        ).scalars().all()

    seen: dict[str, dict] = {}
    for row in rows:
        meta = row.chunk_metadata
        doc_id = meta.get("doc_id", row.doc_id)
        if doc_id not in seen:
            seen[doc_id] = {
                "doc_id": doc_id,
                "title": meta.get("title", "Unknown"),
                "source": meta.get("source", ""),
                "total_chunks": meta.get("total_chunks", 1),
            }
    return list(seen.values())
