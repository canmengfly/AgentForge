"""Basic unit tests for core modules (no external services required)."""
import pytest
from src.core.document_processor import chunk_document, parse_text


def test_parse_text():
    doc = parse_text("Hello world content", "Test Doc")
    assert doc.title == "Test Doc"
    assert doc.content == "Hello world content"
    assert len(doc.doc_id) == 16


def test_chunk_short_document():
    doc = parse_text("Short text.", "Short")
    chunks = chunk_document(doc, chunk_size=512, overlap=0)
    assert len(chunks) == 1
    assert chunks[0].content == "Short text."
    assert chunks[0].doc_id == doc.doc_id


def test_chunk_long_document():
    content = ("This is a sentence. " * 50).strip()
    doc = parse_text(content, "Long Doc")
    chunks = chunk_document(doc, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    # All chunks have same doc_id
    assert all(c.doc_id == doc.doc_id for c in chunks)
    # chunk_index is sequential
    for i, c in enumerate(chunks):
        assert c.metadata["chunk_index"] == i


def test_chunk_metadata():
    doc = parse_text("Some content here.", "Meta Doc")
    doc.metadata["author"] = "Alice"
    chunks = chunk_document(doc, chunk_size=512)
    assert chunks[0].metadata["author"] == "Alice"
    assert chunks[0].metadata["title"] == "Meta Doc"
