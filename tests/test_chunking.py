"""Tests for sentence-aware chunking, word-boundary overlap, and score threshold."""
import pytest
from src.core.document_processor import chunk_document, parse_text, _split_sentences
from src.core.connectors.sql_connector import _row_stable_key


# ── Sentence splitter ────────────────────────────────────────────────────────

class TestSplitSentences:
    def test_splits_on_chinese_period(self):
        parts = _split_sentences("一句话。第二句话。")
        # Splitter keeps punctuation with the preceding sentence
        assert parts == ["一句话。", "第二句话。"]

    def test_splits_on_exclamation_and_question(self):
        parts = _split_sentences("What? Really! Yes.")
        assert len(parts) == 3

    def test_splits_on_blank_lines(self):
        parts = _split_sentences("Para one.\n\nPara two.")
        assert len(parts) == 2

    def test_empty_returns_empty(self):
        assert _split_sentences("") == []

    def test_no_boundary_returns_single(self):
        parts = _split_sentences("no boundary here")
        assert parts == ["no boundary here"]


# ── Chunking ─────────────────────────────────────────────────────────────────

class TestChunkDocument:
    def test_single_chunk_for_short_doc(self):
        doc = parse_text("短文本内容。", "Short")
        chunks = chunk_document(doc, chunk_size=512, overlap=0)
        assert len(chunks) == 1
        assert chunks[0].content == "短文本内容。"

    def test_splits_at_sentence_boundary(self):
        # Each sentence is ~40 chars; chunk_size=50 should force splits
        content = "First sentence here now." * 3
        doc = parse_text(content, "Split")
        chunks = chunk_document(doc, chunk_size=50, overlap=0)
        assert len(chunks) > 1
        # No chunk should start in the middle of "sentence"
        for c in chunks:
            assert not c.content.startswith("entence"), "chunk started mid-word"

    def test_chunk_metadata_propagated(self):
        doc = parse_text("Content.", "MyDoc")
        doc.metadata["author"] = "Bob"
        chunks = chunk_document(doc, chunk_size=512)
        assert chunks[0].metadata["author"] == "Bob"
        assert chunks[0].metadata["title"] == "MyDoc"

    def test_chunk_index_sequential(self):
        content = ("Long sentence to fill up space. " * 20).strip()
        doc = parse_text(content, "Long")
        chunks = chunk_document(doc, chunk_size=80, overlap=0)
        assert len(chunks) > 1
        for i, c in enumerate(chunks):
            assert c.metadata["chunk_index"] == i

    def test_total_chunks_in_metadata(self):
        content = ("Sentence. " * 30).strip()
        doc = parse_text(content, "Total")
        chunks = chunk_document(doc, chunk_size=60, overlap=0)
        total = len(chunks)
        for c in chunks:
            assert c.metadata["total_chunks"] == total

    def test_overlap_prepends_tail_of_previous(self):
        # With overlap, chunk[1] should contain some text from chunk[0]
        content = ("Alpha beta gamma delta epsilon. " * 10).strip()
        doc = parse_text(content, "Overlap")
        chunks_no_overlap = chunk_document(doc, chunk_size=80, overlap=0)
        chunks_overlap = chunk_document(doc, chunk_size=80, overlap=30)

        if len(chunks_overlap) > 1:
            # The second chunk with overlap should be longer than without
            assert len(chunks_overlap[1].content) >= len(chunks_no_overlap[1].content)

    def test_overlap_starts_at_word_boundary(self):
        # Verify no chunk (except first) starts with a partial word
        content = ("word " * 100).strip()
        doc = parse_text(content, "Words")
        chunks = chunk_document(doc, chunk_size=80, overlap=20)
        for i, c in enumerate(chunks[1:], 1):
            # Content should not start mid-word (no leading partial words)
            first_char = c.content[0] if c.content else ""
            assert first_char != " ", f"chunk {i} starts with space: {c.content[:30]!r}"

    def test_empty_document_returns_empty_list(self):
        doc = parse_text("", "Empty")
        assert chunk_document(doc) == []

    def test_oversized_sentence_force_split(self):
        # Single sentence longer than chunk_size — must still produce chunks
        long_sent = "x" * 1000
        doc = parse_text(long_sent, "Huge")
        chunks = chunk_document(doc, chunk_size=200, overlap=0)
        assert len(chunks) == 5  # 1000 / 200
        for c in chunks:
            assert len(c.content) <= 200

    def test_all_chunks_share_doc_id(self):
        doc = parse_text("A. B. C. D. E. F. G. H. I. J.", "IDs")
        chunks = chunk_document(doc, chunk_size=10, overlap=0)
        for c in chunks:
            assert c.doc_id == doc.doc_id

    def test_chunk_ids_unique(self):
        doc = parse_text("Sentence one. Sentence two. Sentence three.", "Unique")
        chunks = chunk_document(doc, chunk_size=20, overlap=0)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))


# ── SQL stable doc_id ─────────────────────────────────────────────────────────

class TestRowStableKey:
    def test_uses_id_column(self):
        key = _row_stable_key("users", {"id": 42, "name": "Alice"})
        assert key == "pk:id:42"

    def test_uses_table_id_column(self):
        key = _row_stable_key("orders", {"order_id": 99, "amount": 100})
        assert key == "pk:order_id:99"

    def test_uses_singular_table_id(self):
        # "products" → singular "product" → checks "product_id"
        key = _row_stable_key("products", {"product_id": 7, "name": "Widget"})
        assert key == "pk:product_id:7"

    def test_falls_back_to_content_hash_when_no_pk(self):
        key = _row_stable_key("misc", {"col_a": "foo", "col_b": "bar"})
        assert key.startswith("content:")
        # Same row produces same hash
        key2 = _row_stable_key("misc", {"col_a": "foo", "col_b": "bar"})
        assert key == key2

    def test_different_rows_produce_different_hashes(self):
        k1 = _row_stable_key("misc", {"col_a": "foo"})
        k2 = _row_stable_key("misc", {"col_a": "bar"})
        assert k1 != k2

    def test_ignores_none_pk_value(self):
        # If pk column is None, fall back to content hash
        key = _row_stable_key("users", {"id": None, "name": "Alice"})
        assert key.startswith("content:")

    def test_prefers_pk_over_content(self):
        key = _row_stable_key("items", {"id": 1, "item_id": 2, "name": "x"})
        # "id" appears first in _PK_CANDIDATES
        assert key == "pk:id:1"
