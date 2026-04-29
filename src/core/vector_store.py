"""Vector store façade — routes to ChromaDB or pgvector based on VECTOR_BACKEND config."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import settings


@dataclass
class SearchResult:
    chunk_id: str
    doc_id: str
    content: str
    score: float
    metadata: dict


def _backend():
    if settings.vector_backend == "pgvector":
        from . import pg_vector_store as _b
    else:
        from . import chroma_vector_store as _b
    return _b


def init_vector_db():
    """Called once at startup to create tables / indexes."""
    if settings.vector_backend == "pgvector":
        from .pg_vector_store import init_db
        init_db()


def list_collections() -> list[dict[str, Any]]:
    return _backend().list_collections()


def add_document(doc, collection: str = "default") -> list[str]:
    return _backend().add_document(doc, collection)


def delete_document(doc_id: str, collection: str = "default") -> int:
    return _backend().delete_document(doc_id, collection)


def search(
    query: str,
    collection: str = "default",
    top_k: int | None = None,
    where: dict | None = None,
) -> list[SearchResult]:
    raw = _backend().search(query, collection, top_k, where)
    threshold = settings.search_score_threshold
    return [
        SearchResult(
            chunk_id=r.chunk_id,
            doc_id=r.doc_id,
            content=r.content,
            score=r.score,
            metadata=r.metadata,
        )
        for r in raw
        if r.score >= threshold
    ]


def get_document_chunks(doc_id: str, collection: str = "default") -> list[dict]:
    return _backend().get_document_chunks(doc_id, collection)


def delete_collection(collection: str) -> int:
    return _backend().delete_collection(collection)


def list_chunks(
    collection: str,
    offset: int = 0,
    limit: int = 20,
    doc_id: str | None = None,
) -> tuple[list[dict], int]:
    return _backend().list_chunks(collection, offset=offset, limit=limit, doc_id=doc_id)


def list_documents_in_collection(collection: str) -> list[dict]:
    """Return deduplicated document summaries for a collection (backend-agnostic)."""
    return _backend().list_documents_in_collection(collection)
