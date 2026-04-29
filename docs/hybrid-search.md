# Hybrid Search Architecture

AgentForge retrieves relevant document chunks using a multi-stage pipeline that combines vector similarity, BM25 term-frequency ranking, and an optional cross-encoder reranker.

---

## Overview

```
User query
    │
    ▼
┌───────────────────────────────────────────┐
│  Stage 1: Vector Fan-out                  │
│  Embed query → cosine similarity search   │
│  across all target collections            │
└─────────────────────┬─────────────────────┘
                      │
                      ▼
┌───────────────────────────────────────────┐
│  Stage 2: BM25 Re-scoring (SQL sources)   │
│  Applied when collections include SQL-    │
│  type data sources (MySQL, PG, Oracle,    │
│  SQL Server, TiDB, OceanBase, Doris,      │
│  ClickHouse, Hive, Snowflake)             │
└─────────────────────┬─────────────────────┘
                      │
                      ▼
┌───────────────────────────────────────────┐
│  Stage 3: Cross-encoder Reranking         │
│  Optional — enabled when RERANKER_MODEL   │
│  is set. Score = model(query, chunk)      │
└─────────────────────┬─────────────────────┘
                      │
                      ▼
┌───────────────────────────────────────────┐
│  Stage 4: Dedup + Top-K                   │
│  Deduplicate by doc_id, return top_k      │
└───────────────────────────────────────────┘
```

---

## Stage 1: Vector Similarity

All queries are encoded using the configured `EMBEDDING_MODEL` (default: `all-MiniLM-L6-v2`). The encoded vector is compared against stored chunk embeddings using cosine similarity.

- **Backend:** ChromaDB or pgvector (configurable via `VECTOR_BACKEND`)
- **Initial candidate pool:** `top_k * 4` candidates per collection to ensure the reranking stages have enough material to work with

### Cross-collection search

`POST /me/search/all` fans out the query to every collection belonging to the user. Results are merged before BM25 and reranking stages.

---

## Stage 2: BM25 Re-scoring

BM25 (Best Matching 25) is a classical probabilistic ranking function that scores documents by term frequency relative to the document length and corpus-wide inverse document frequency.

This stage is applied when the result set includes chunks from collections backed by SQL-type data sources. SQL sources produce structured `key: value` row content where exact keyword matching is often more effective than semantic distance.

### Formula

```
BM25(q, d) = Σ IDF(tᵢ) · (f(tᵢ,d) · (k₁+1)) / (f(tᵢ,d) + k₁ · (1 - b + b · |d|/avgdl))
```

Where:
- `f(tᵢ,d)` = frequency of term `tᵢ` in document `d`
- `|d|` = document length
- `avgdl` = average document length in the corpus
- `k₁ = 1.5`, `b = 0.75` (standard BM25 parameters)

### Final score fusion

Vector similarity and BM25 scores are normalized to [0,1] and combined:

```
final_score = α · vector_score + (1-α) · bm25_score
```

The mixing weight `α` defaults to `0.5` for SQL-backed collections and `1.0` for purely vector sources.

---

## Stage 3: Cross-encoder Reranking (Optional)

When `RERANKER_MODEL` is set, a cross-encoder model scores each (query, chunk) pair directly. Cross-encoders see both texts jointly, enabling attention across the full pair — substantially more accurate than bi-encoder similarity but more expensive to compute.

### Enabling reranking

```env
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

### Recommended models

| Model | Size | Latency | Notes |
|---|---|---|---|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | ~68 MB | ~50ms/chunk | Best speed/quality balance |
| `cross-encoder/ms-marco-MiniLM-L-12-v2` | ~117 MB | ~100ms/chunk | Higher quality |
| `cross-encoder/ms-marco-electra-base` | ~435 MB | ~200ms/chunk | Highest quality |

Reranking happens on CPU by default. For large `top_k` values, consider GPU inference or a smaller model.

### Reranking behavior

1. Take the merged, BM25-adjusted candidate list (up to `top_k * 4` chunks)
2. Score each `(query, chunk.content)` pair with the cross-encoder
3. Sort descending by cross-encoder score
4. Return the top `top_k` results

---

## Stage 4: Dedup + Top-K

After all scoring stages, results are deduplicated by `doc_id`. If the same chunk appears from multiple collection fan-out calls, only the highest-scored instance is kept. The final list is truncated to `top_k`.

---

## Configuration Reference

| Variable | Default | Effect |
|---|---|---|
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Bi-encoder model for vector search |
| `EMBEDDING_DIM` | `384` | Must match the model's output dimension |
| `RERANKER_MODEL` | `""` | Cross-encoder model; empty = disabled |
| `VECTOR_BACKEND` | `chroma` | `chroma` or `pgvector` |

---

## Search Endpoints

### Search within a collection

```http
POST /me/search
Content-Type: application/json
Authorization: Bearer aft_...

{
  "query": "string",
  "collection": "my-collection",
  "top_k": 5
}
```

### Search across all collections

```http
POST /me/search/all
Content-Type: application/json
Authorization: Bearer aft_...

{
  "query": "string",
  "top_k": 10
}
```

### Response format

```json
{
  "results": [
    {
      "chunk_id": "abc123",
      "doc_id": "def456",
      "content": "...",
      "score": 0.87,
      "metadata": {
        "source_type": "mysql",
        "table": "products",
        "database": "shop"
      }
    }
  ]
}
```

---

## Tuning Recommendations

| Scenario | Recommendation |
|---|---|
| Most content is prose (docs, wikis) | Keep `RERANKER_MODEL` empty, rely on vector similarity |
| Mixed structured + unstructured | Enable reranker with `ms-marco-MiniLM-L-6-v2` |
| High-precision RAG on SQL data | Enable reranker + set `top_k ≥ 20` for wider candidate pool |
| Low-latency requirement | Disable reranker, use `all-MiniLM-L6-v2` with small `top_k` |
| Multilingual content | Use a multilingual embedding model, e.g. `paraphrase-multilingual-MiniLM-L12-v2` |
