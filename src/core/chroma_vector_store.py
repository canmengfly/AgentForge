"""ChromaDB backend (default — zero external dependencies)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from .config import settings
from .document_processor import ParsedDocument, chunk_document
from .embeddings import embed_query, embed_texts


@dataclass
class SearchResult:
    chunk_id: str
    doc_id: str
    content: str
    score: float
    metadata: dict


@lru_cache(maxsize=1)
def _client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(
        path=str(settings.chroma_persist_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _collection(name: str) -> chromadb.Collection:
    return _client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def list_collections() -> list[dict[str, Any]]:
    cols = _client().list_collections()
    result = []
    for col in cols:
        c = _client().get_collection(col.name)
        result.append({"name": col.name, "count": c.count()})
    return result


def add_document(doc: ParsedDocument, collection: str = "default") -> list[str]:
    chunks = chunk_document(doc, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        return []

    col = _collection(collection)
    embeddings = embed_texts([c.content for c in chunks])
    col.upsert(
        ids=[c.chunk_id for c in chunks],
        embeddings=embeddings,
        documents=[c.content for c in chunks],
        metadatas=[
            {**c.metadata, "doc_id": c.doc_id, "collection": collection}
            for c in chunks
        ],
    )
    return [c.chunk_id for c in chunks]


def delete_document(doc_id: str, collection: str = "default") -> int:
    col = _collection(collection)
    results = col.get(where={"doc_id": doc_id})
    ids = results["ids"]
    if ids:
        col.delete(ids=ids)
    return len(ids)


def search(
    query: str,
    collection: str = "default",
    top_k: int | None = None,
    where: dict | None = None,
) -> list[SearchResult]:
    k = top_k or settings.default_top_k
    col = _collection(collection)
    if col.count() == 0:
        return []

    vector = embed_query(query)
    kwargs: dict[str, Any] = {"query_embeddings": [vector], "n_results": min(k, col.count())}
    if where:
        kwargs["where"] = where

    results = col.query(**kwargs)
    output: list[SearchResult] = []
    for i, chunk_id in enumerate(results["ids"][0]):
        distance = results["distances"][0][i]
        score = 1.0 - distance
        meta = results["metadatas"][0][i]
        output.append(
            SearchResult(
                chunk_id=chunk_id,
                doc_id=meta.get("doc_id", ""),
                content=results["documents"][0][i],
                score=round(score, 4),
                metadata=meta,
            )
        )
    return sorted(output, key=lambda r: r.score, reverse=True)


def get_document_chunks(doc_id: str, collection: str = "default") -> list[dict]:
    col = _collection(collection)
    results = col.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
    return [
        {"chunk_id": cid, "content": doc, "metadata": meta}
        for cid, doc, meta in zip(
            results["ids"], results["documents"], results["metadatas"]
        )
    ]


def delete_collection(collection: str) -> int:
    """Delete an entire collection. Returns the number of chunks that were in it."""
    col = _collection(collection)
    count = col.count()
    _client().delete_collection(collection)
    return count


def list_chunks(
    collection: str,
    offset: int = 0,
    limit: int = 20,
    doc_id: str | None = None,
) -> tuple[list[dict], int]:
    """Return paginated chunks, optionally filtered by doc_id. Returns (chunks, total)."""
    col = _collection(collection)
    where = {"doc_id": doc_id} if doc_id else None

    # Count total
    count_kwargs: dict[str, Any] = {"include": []}
    if where:
        count_kwargs["where"] = where
    total = len(col.get(**count_kwargs)["ids"])

    if total == 0:
        return [], 0

    get_kwargs: dict[str, Any] = {
        "include": ["documents", "metadatas"],
        "limit": limit,
        "offset": offset,
    }
    if where:
        get_kwargs["where"] = where

    results = col.get(**get_kwargs)
    chunks = [
        {"chunk_id": cid, "content": doc, "metadata": meta}
        for cid, doc, meta in zip(
            results["ids"], results["documents"], results["metadatas"]
        )
    ]
    return chunks, total


def list_documents_in_collection(collection: str) -> list[dict]:
    col = _collection(collection)
    results = col.get(include=["metadatas"])
    seen: dict[str, dict] = {}
    for meta in results["metadatas"]:
        doc_id = meta.get("doc_id", "")
        if doc_id not in seen:
            seen[doc_id] = {
                "doc_id": doc_id,
                "title": meta.get("title", "Unknown"),
                "source": meta.get("source", ""),
                "total_chunks": meta.get("total_chunks", 1),
            }
    return list(seen.values())
