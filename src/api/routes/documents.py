from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src.core.document_processor import parse_file, parse_text
from src.core.vector_store import add_document, delete_document, get_document_chunks

router = APIRouter(prefix="/documents", tags=["documents"])


class TextDocumentRequest(BaseModel):
    title: str
    content: str
    collection: str = "default"
    metadata: dict = {}


class DocumentResponse(BaseModel):
    doc_id: str
    title: str
    collection: str
    chunk_count: int


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    collection: Annotated[str, Query()] = "default",
):
    if not file.filename:
        raise HTTPException(400, "Filename required")

    allowed = {".txt", ".md", ".pdf", ".docx", ".html", ".htm"}
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Allowed: {allowed}")

    raw = await file.read()
    import io
    doc = parse_file(io.BytesIO(raw), file.filename)
    chunk_ids = add_document(doc, collection)

    return DocumentResponse(
        doc_id=doc.doc_id,
        title=doc.title,
        collection=collection,
        chunk_count=len(chunk_ids),
    )


@router.post("/text", response_model=DocumentResponse)
async def add_text_document(body: TextDocumentRequest):
    doc = parse_text(body.content, body.title)
    doc.metadata.update(body.metadata)
    chunk_ids = add_document(doc, body.collection)
    return DocumentResponse(
        doc_id=doc.doc_id,
        title=doc.title,
        collection=body.collection,
        chunk_count=len(chunk_ids),
    )


@router.get("/{doc_id}/chunks")
async def get_chunks(doc_id: str, collection: str = "default"):
    chunks = get_document_chunks(doc_id, collection)
    if not chunks:
        raise HTTPException(404, f"Document '{doc_id}' not found in collection '{collection}'")
    return {"doc_id": doc_id, "collection": collection, "chunks": chunks}


@router.delete("/{doc_id}")
async def remove_document(doc_id: str, collection: str = "default"):
    deleted = delete_document(doc_id, collection)
    if deleted == 0:
        raise HTTPException(404, f"Document '{doc_id}' not found in collection '{collection}'")
    return {"deleted_chunks": deleted, "doc_id": doc_id}
