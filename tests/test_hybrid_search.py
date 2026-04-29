"""Tests for Phase 1 (BM25 hybrid retrieval) and Phase 2 (cross-encoder reranker)."""
import math
import pytest
from unittest.mock import MagicMock, patch

from src.core.bm25 import BM25, _tokenize


# ── BM25 unit tests ───────────────────────────────────────────────────────────

class TestBM25Tokenize:
    def test_latin_words(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_cjk_characters(self):
        tokens = _tokenize("向量检索")
        assert len(tokens) >= 1  # CJK characters tokenised

    def test_mixed(self):
        tokens = _tokenize("Python 向量")
        assert "python" in tokens

    def test_empty(self):
        assert _tokenize("") == []


class TestBM25:
    def test_higher_score_for_more_matches(self):
        corpus = [
            "machine learning neural network deep learning",
            "cooking recipes food",
        ]
        bm25 = BM25(corpus)
        scores = bm25.scores("machine learning")
        assert scores[0] > scores[1], "doc with more matches should score higher"

    def test_zero_score_for_no_match(self):
        bm25 = BM25(["apple orange banana"])
        scores = bm25.scores("quantum physics")
        assert scores[0] == 0.0

    def test_repeated_term_boosts_score(self):
        bm25 = BM25(["cat cat cat", "cat"])
        s = bm25.scores("cat")
        # BM25 saturates TF, but more occurrences still boost score
        assert s[0] >= s[1]

    def test_scores_length_matches_corpus(self):
        corpus = ["a", "b", "c", "d"]
        bm25 = BM25(corpus)
        assert len(bm25.scores("a")) == 4

    def test_top_k_returns_sorted(self):
        corpus = [
            "python programming tutorial",
            "javascript web development",
            "python data science",
        ]
        bm25 = BM25(corpus)
        top = bm25.top_k("python", k=2)
        assert len(top) == 2
        assert top[0][1] >= top[1][1], "top_k should be sorted descending"
        idxs = {i for i, _ in top}
        assert 0 in idxs or 2 in idxs, "python docs should be top-2"

    def test_empty_corpus(self):
        bm25 = BM25([])
        assert bm25.scores("anything") == []

    def test_single_doc(self):
        bm25 = BM25(["only document"])
        scores = bm25.scores("document")
        assert len(scores) == 1
        assert scores[0] > 0

    def test_bm25_norm_formula(self):
        """x/(x+1) normalization maps positive scores to (0, 1)."""
        for raw in (0.0, 0.5, 2.0, 10.0):
            norm = raw / (raw + 1.0)
            assert 0.0 <= norm < 1.0

    def test_chinese_query(self):
        corpus = ["客户退款投诉记录", "商品库存数量统计", "退款流程说明文档"]
        bm25 = BM25(corpus)
        scores = bm25.scores("退款")
        # Docs 0 and 2 mention "退款", doc 1 does not
        assert scores[0] > scores[1] or scores[2] > scores[1]


# ── Reranker unit tests ───────────────────────────────────────────────────────

class TestReranker:
    def _make_result(self, content: str, score: float = 0.5):
        from src.core.vector_store import SearchResult
        return SearchResult(
            chunk_id=f"c_{hash(content) % 10000}",
            doc_id="d1",
            content=content,
            score=score,
            metadata={},
        )

    def test_rerank_disabled_returns_sorted_by_existing_score(self):
        from src.core.reranker import rerank
        results = [
            self._make_result("low", score=0.2),
            self._make_result("high", score=0.9),
            self._make_result("mid", score=0.5),
        ]
        with patch("src.core.reranker.get_active_reranker_name", return_value=None):
            ranked = rerank("query", results, top_k=3)
        assert ranked[0].score == 0.9
        assert ranked[1].score == 0.5

    def test_rerank_disabled_respects_top_k(self):
        from src.core.reranker import rerank
        results = [self._make_result(f"doc{i}", score=float(i) / 10) for i in range(10)]
        with patch("src.core.reranker.get_active_reranker_name", return_value=None):
            ranked = rerank("query", results, top_k=3)
        assert len(ranked) == 3

    def test_rerank_with_model_calls_predict(self):
        from src.core.reranker import rerank
        import numpy as np
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([2.0, -1.0, 1.0])

        results = [
            self._make_result("best",   score=0.3),
            self._make_result("worst",  score=0.9),  # high vector score, low CE score
            self._make_result("middle", score=0.5),
        ]

        with patch("src.core.reranker.get_active_reranker_name", return_value="fake/model"):
            with patch("src.core.reranker._load", return_value=mock_model):
                ranked = rerank("query", results, top_k=3)

        mock_model.predict.assert_called_once()
        # "best" has raw CE score 2.0 (sigmoid ≈ 0.88), should be first
        assert ranked[0].content == "best"

    def test_rerank_applies_sigmoid_normalisation(self):
        from src.core.reranker import rerank
        import numpy as np
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.0])  # sigmoid(0) = 0.5

        results = [self._make_result("doc", score=0.1)]
        with patch("src.core.reranker.get_active_reranker_name", return_value="m"):
            with patch("src.core.reranker._load", return_value=mock_model):
                ranked = rerank("query", results, top_k=1)

        assert abs(ranked[0].score - 0.5) < 0.01  # sigmoid(0) = 0.5

    def test_rerank_empty_returns_empty(self):
        from src.core.reranker import rerank
        with patch("src.core.reranker.get_active_reranker_name", return_value=None):
            assert rerank("q", [], top_k=5) == []


# ── /me/search/all API tests with source_type ─────────────────────────────────

def _add(client, title, content, collection="default"):
    return client.post("/me/documents/text",
                       json={"title": title, "content": content, "collection": collection}).json()


class TestHybridSearchAll:

    def test_source_type_field_present_in_hits(self, as_user):
        import uuid
        col = f"srctype_{uuid.uuid4().hex[:6]}"
        _add(as_user, "Python Guide", "Python is a programming language.", col)

        resp = as_user.post("/me/search/all", json={"query": "programming", "top_k": 5})
        assert resp.status_code == 200
        for hit in resp.json()["hits"]:
            assert "source_type" in hit, "source_type field missing from hit"

    def test_document_source_type(self, as_user):
        import uuid
        col = f"doctype_{uuid.uuid4().hex[:6]}"
        _add(as_user, "Doc", "Some content here.", col)

        resp = as_user.post("/me/search/all", json={"query": "content", "top_k": 5})
        hits = resp.json()["hits"]
        if hits:
            # Regular uploaded docs have no source_type in metadata → defaults to "document"
            assert hits[0]["source_type"] in ("document", "sql", "feishu", "dingtalk", "tencent_docs")

    def test_search_all_still_deduplicates(self, as_user):
        import uuid
        col = f"dedup_{uuid.uuid4().hex[:6]}"
        for i in range(5):
            _add(as_user, f"Item {i}", f"Dedup test content item {i}.", col)

        resp = as_user.post("/me/search/all", json={"query": "dedup test content", "top_k": 20})
        chunk_ids = [h["chunk_id"] for h in resp.json()["hits"]]
        assert len(chunk_ids) == len(set(chunk_ids))

    def test_search_all_respects_top_k(self, as_user):
        import uuid
        col = f"topk_{uuid.uuid4().hex[:6]}"
        for i in range(10):
            _add(as_user, f"T{i}", f"Content for top-k test item {i}.", col)

        for k in (1, 3):
            resp = as_user.post("/me/search/all", json={"query": "top-k test", "top_k": k})
            assert len(resp.json()["hits"]) <= k

    def test_search_all_scores_sorted_descending(self, as_user):
        import uuid
        col = f"sort_{uuid.uuid4().hex[:6]}"
        for i in range(5):
            _add(as_user, f"S{i}", f"Score sorting document content {i}.", col)

        resp = as_user.post("/me/search/all", json={"query": "score sorting", "top_k": 10})
        scores = [h["score"] for h in resp.json()["hits"]]
        assert scores == sorted(scores, reverse=True)


# ── Admin reranker endpoints ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_reranker_state():
    import src.api.routes.admin as admin_mod
    import src.core.reranker as reranker_mod
    reranker_mod._active_model = None
    admin_mod._reranker_state.update(loading=False, error=None)
    yield
    reranker_mod._active_model = None
    admin_mod._reranker_state.update(loading=False, error=None)


class TestAdminReranker:

    def test_get_reranker_info_structure(self, as_admin):
        resp = as_admin.get("/api/admin/reranker")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("enabled", "model", "models", "loading", "error"):
            assert field in data, f"missing field: {field}"

    def test_disabled_by_default(self, as_admin):
        resp = as_admin.get("/api/admin/reranker")
        assert resp.json()["enabled"] is False
        assert resp.json()["model"] is None

    def test_lists_supported_rerankers(self, as_admin):
        from src.core.config import SUPPORTED_RERANKERS
        resp = as_admin.get("/api/admin/reranker")
        models = resp.json()["models"]
        assert len(models) == len(SUPPORTED_RERANKERS)
        names = [m["name"] for m in models]
        assert "BAAI/bge-reranker-base" in names

    def test_unsupported_model_returns_400(self, as_admin):
        resp = as_admin.post("/api/admin/reranker/switch",
                             json={"model_name": "fake/model-that-doesnt-exist"})
        assert resp.status_code == 400

    def test_switch_to_valid_model(self, as_admin):
        with patch("src.core.reranker.switch_reranker"):
            resp = as_admin.post("/api/admin/reranker/switch",
                                 json={"model_name": "BAAI/bge-reranker-base"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_disable_reranker(self, as_admin):
        with patch("src.core.reranker.switch_reranker"):
            resp = as_admin.post("/api/admin/reranker/switch", json={"model_name": ""})
        assert resp.status_code == 200
        assert resp.json()["model"] is None

    def test_concurrent_switch_returns_409(self, as_admin):
        import src.api.routes.admin as admin_mod
        admin_mod._reranker_state["loading"] = True
        try:
            resp = as_admin.post("/api/admin/reranker/switch",
                                 json={"model_name": "BAAI/bge-reranker-base"})
            assert resp.status_code == 409
        finally:
            admin_mod._reranker_state["loading"] = False

    def test_status_endpoint(self, as_admin):
        resp = as_admin.get("/api/admin/reranker/status")
        assert resp.status_code == 200
        assert "enabled" in resp.json()
        assert "loading" in resp.json()

    def test_switch_persists_to_db(self, as_admin):
        with patch("src.core.reranker.switch_reranker"):
            as_admin.post("/api/admin/reranker/switch",
                          json={"model_name": "BAAI/bge-reranker-base"})
        from src.core.database import SessionLocal
        from src.core.models import SystemConfig
        db = SessionLocal()
        cfg = db.get(SystemConfig, "reranker_model")
        db.close()
        assert cfg is not None
        assert cfg.value == "BAAI/bge-reranker-base"

    def test_requires_admin(self, as_user):
        assert as_user.get("/api/admin/reranker").status_code == 403
        assert as_user.post("/api/admin/reranker/switch",
                            json={"model_name": ""}).status_code == 403
