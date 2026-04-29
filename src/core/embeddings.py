from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# Runtime override; None means use settings.embedding_model
_active_model: str | None = None


def get_active_model_name() -> str:
    return _active_model or settings.embedding_model


@lru_cache(maxsize=None)  # keyed per model name — supports multiple cached models
def _load_model(name: str) -> "SentenceTransformer":
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError("sentence-transformers required: pip install sentence-transformers") from e
    return SentenceTransformer(name, device=settings.embedding_device)


def get_model() -> "SentenceTransformer":
    return _load_model(get_active_model_name())


def switch_model(name: str) -> None:
    """Switch active embedding model. Downloads the model if not cached. Blocking."""
    global _active_model
    _active_model = name
    _load_model(name)  # pre-load / download now


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = get_model().encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]
