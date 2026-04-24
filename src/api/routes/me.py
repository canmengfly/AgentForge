"""User-scoped API — all operations are isolated to the current user's namespace."""
from __future__ import annotations

import io
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from src.core.deps import CurrentUser, DBSession
from src.core.document_processor import parse_file, parse_text
from src.core.models import APIToken
from src.core.vector_store import (
    add_document,
    delete_collection,
    delete_document,
    get_document_chunks,
    list_chunks,
    list_collections,
    list_documents_in_collection,
    search,
)

router = APIRouter(prefix="/me", tags=["me"])

# Collection namespace helpers
def _col(user_id: int, name: str = "default") -> str:
    return f"u{user_id}_{name}"

def _strip(user_id: int, col_name: str) -> str:
    prefix = f"u{user_id}_"
    return col_name[len(prefix):] if col_name.startswith(prefix) else col_name


class TextDocRequest(BaseModel):
    title: str
    content: str
    collection: str = "default"
    metadata: dict = {}


class CreateTokenRequest(BaseModel):
    name: str


class SearchRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = Field(default=5, ge=1, le=20)


@router.get("/collections")
async def my_collections(current_user: CurrentUser):
    all_cols = list_collections()
    prefix = f"u{current_user.id}_"
    mine = [
        {"name": _strip(current_user.id, c["name"]), "count": c["count"]}
        for c in all_cols
        if c["name"].startswith(prefix)
    ]
    return {"collections": mine}


@router.post("/documents/upload")
async def upload_doc(
    file: UploadFile,
    current_user: CurrentUser,
    collection: Annotated[str, Query()] = "default",
):
    if not file.filename:
        raise HTTPException(400, "Filename required")
    allowed = {".txt", ".md", ".pdf", ".docx", ".html", ".htm"}
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported type '{suffix}'")

    raw = await file.read()
    doc = parse_file(io.BytesIO(raw), file.filename)
    chunk_ids = add_document(doc, _col(current_user.id, collection))
    return {"doc_id": doc.doc_id, "title": doc.title, "collection": collection, "chunk_count": len(chunk_ids)}


@router.post("/documents/text")
async def add_text(body: TextDocRequest, current_user: CurrentUser):
    doc = parse_text(body.content, body.title)
    doc.metadata.update(body.metadata)
    chunk_ids = add_document(doc, _col(current_user.id, body.collection))
    return {"doc_id": doc.doc_id, "title": doc.title, "collection": body.collection, "chunk_count": len(chunk_ids)}


@router.get("/documents")
async def list_my_docs(current_user: CurrentUser, collection: str = "default"):
    col = _col(current_user.id, collection)
    docs = list_documents_in_collection(col)
    for d in docs:
        d["collection"] = collection
    return {"collection": collection, "documents": docs}


@router.delete("/collections/{collection_name}")
async def delete_my_collection(collection_name: str, current_user: CurrentUser):
    col = _col(current_user.id, collection_name)
    deleted_chunks = delete_collection(col)
    return {"ok": True, "collection": collection_name, "deleted_chunks": deleted_chunks}


@router.get("/chunks")
async def list_my_chunks(
    current_user: CurrentUser,
    collection: str = "default",
    doc_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    col = _col(current_user.id, collection)
    offset = (page - 1) * page_size
    chunks, total = list_chunks(col, offset=offset, limit=page_size, doc_id=doc_id)
    for c in chunks:
        c["metadata"].pop("collection", None)
    return {
        "collection": collection,
        "total": total,
        "page": page,
        "page_size": page_size,
        "chunks": chunks,
    }


@router.delete("/documents/{doc_id}")
async def delete_my_doc(doc_id: str, current_user: CurrentUser, collection: str = "default"):
    deleted = delete_document(doc_id, _col(current_user.id, collection))
    if deleted == 0:
        raise HTTPException(404, "Document not found")
    return {"ok": True, "deleted_chunks": deleted}


@router.get("/tokens")
async def list_my_tokens(current_user: CurrentUser, db: DBSession):
    tokens = (
        db.query(APIToken)
        .filter(APIToken.user_id == current_user.id)
        .order_by(APIToken.created_at.desc())
        .all()
    )
    return {
        "tokens": [
            {
                "id": t.id,
                "name": t.name,
                "prefix": t.prefix,
                "created_at": t.created_at.isoformat(),
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            }
            for t in tokens
        ]
    }


@router.post("/tokens", status_code=201)
async def create_my_token(body: CreateTokenRequest, current_user: CurrentUser, db: DBSession):
    from src.core.auth import generate_api_token, hash_api_token

    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Token name required")
    full_token, prefix = generate_api_token()
    token_hash = hash_api_token(full_token)
    api_token = APIToken(user_id=current_user.id, name=name, token_hash=token_hash, prefix=prefix)
    db.add(api_token)
    db.commit()
    db.refresh(api_token)
    return {
        "id": api_token.id,
        "name": api_token.name,
        "prefix": prefix,
        "token": full_token,
        "created_at": api_token.created_at.isoformat(),
    }


@router.delete("/tokens/{token_id}")
async def delete_my_token(token_id: int, current_user: CurrentUser, db: DBSession):
    api_token = (
        db.query(APIToken)
        .filter(APIToken.id == token_id, APIToken.user_id == current_user.id)
        .first()
    )
    if not api_token:
        raise HTTPException(404, "Token not found")
    db.delete(api_token)
    db.commit()
    return {"ok": True}


@router.post("/search")
async def my_search(body: SearchRequest, current_user: CurrentUser):
    results = search(body.query, _col(current_user.id, body.collection), top_k=body.top_k)
    return {
        "query": body.query,
        "collection": body.collection,
        "hits": [
            {
                "chunk_id": r.chunk_id,
                "doc_id": r.doc_id,
                "content": r.content,
                "score": r.score,
                "title": r.metadata.get("title", ""),
                "source": r.metadata.get("source", ""),
            }
            for r in results
        ],
    }
