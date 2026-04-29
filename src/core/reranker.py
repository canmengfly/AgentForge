"""Cross-encoder reranker — sentence-transformers CrossEncoder (no extra deps)."""
from __future__ import annotations

import math
from functools import lru_cache

# Runtime override (set via admin API, persisted to SystemConfig)
_active_model: str | None = None


@lru_cache(maxsize=None)
def _load(model_name: str):
    from sentence_transformers import CrossEncoder
    from .config import settings
    return CrossEncoder(model_name, device=settings.embedding_device)


def get_active_reranker_name() -> str | None:
    if _active_model is not None:
        return _active_model or None  # "" → None
    from .config import settings
    return settings.reranker_model or None


def is_enabled() -> bool:
    return bool(get_active_reranker_name())


def switch_reranker(model_name: str) -> None:
    """Update the active reranker and pre-load the model (blocking)."""
    global _active_model
    _active_model = model_name  # "" means disabled
    if model_name:
        _load(model_name)  # warm the cache


def get_info() -> dict:
    return {
        "enabled": is_enabled(),
        "model": get_active_reranker_name(),
    }


def rerank(query: str, candidates: list, top_k: int) -> list:
    """Re-score *candidates* with a cross-encoder and return top_k sorted by score.

    Each candidate must expose `.content` (str) and `.score` (float, mutated in place).
    Falls back to sort-by-existing-score when no reranker is configured.
    """
    model_name = get_active_reranker_name()
    if not model_name or not candidates:
        return sorted(candidates, key=lambda r: r.score, reverse=True)[:top_k]

    model = _load(model_name)
    pairs = [(query, r.content) for r in candidates]
    raw_scores = model.predict(pairs)

    # Sigmoid maps raw cross-encoder logits → (0, 1) — consistent across models
    for r, s in zip(candidates, raw_scores):
        r.score = round(1.0 / (1.0 + math.exp(-float(s))), 4)

    return sorted(candidates, key=lambda r: r.score, reverse=True)[:top_k]
