from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_model() -> "SentenceTransformer":
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError("sentence-transformers required: pip install sentence-transformers") from e
    return SentenceTransformer(settings.embedding_model, device=settings.embedding_device)


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_model()
    vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]
