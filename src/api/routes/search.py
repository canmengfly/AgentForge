from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.core.vector_store import search

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = Field(default=5, ge=1, le=50)
    filters: dict | None = None


class SearchHit(BaseModel):
    chunk_id: str
    doc_id: str
    content: str
    score: float
    metadata: dict


class SearchResponse(BaseModel):
    query: str
    collection: str
    hits: list[SearchHit]


@router.post("", response_model=SearchResponse)
async def semantic_search(body: SearchRequest):
    results = search(
        query=body.query,
        collection=body.collection,
        top_k=body.top_k,
        where=body.filters,
    )
    return SearchResponse(
        query=body.query,
        collection=body.collection,
        hits=[
            SearchHit(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                content=r.content,
                score=r.score,
                metadata=r.metadata,
            )
            for r in results
        ],
    )
