from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings

SUPPORTED_RERANKERS: list[dict] = [
    {
        "name": "BAAI/bge-reranker-base",
        "size_mb": 280,
        "lang": "中英文",
        "desc": "轻量跨语言重排序，推荐首选",
    },
    {
        "name": "BAAI/bge-reranker-large",
        "size_mb": 560,
        "lang": "中英文",
        "desc": "高精度重排序，适合高质量场景",
    },
    {
        "name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "size_mb": 80,
        "lang": "英文",
        "desc": "极轻量英文重排序",
    },
]

SUPPORTED_MODELS: list[dict] = [
    {
        "name": "all-MiniLM-L6-v2",
        "dim": 384,
        "lang": "英文",
        "size_mb": 80,
        "desc": "默认轻量英文模型，速度快",
    },
    {
        "name": "paraphrase-multilingual-MiniLM-L12-v2",
        "dim": 384,
        "lang": "多语言",
        "size_mb": 120,
        "desc": "轻量多语言，中英文基础兼容",
    },
    {
        "name": "BAAI/bge-small-zh-v1.5",
        "dim": 512,
        "lang": "中文",
        "size_mb": 95,
        "desc": "中文轻量模型，速度与质量均衡",
    },
    {
        "name": "BAAI/bge-m3",
        "dim": 1024,
        "lang": "多语言",
        "size_mb": 570,
        "desc": "多语言高精度，中英文强力兼顾",
    },
    {
        "name": "BAAI/bge-large-zh-v1.5",
        "dim": 1024,
        "lang": "中文",
        "size_mb": 670,
        "desc": "中文最高精度，推荐中文知识库",
    },
]


class Settings(BaseSettings):
    app_name: str = "Agent Knowledge Platform"
    version: str = "0.1.0"

    # Storage
    data_dir: Path = Path("data")
    chroma_persist_dir: Path = Path("data/chroma")

    # Vector backend: "chroma" (default, zero-config) or "pgvector" (PostgreSQL)
    vector_backend: Literal["chroma", "pgvector"] = "chroma"
    # Required when vector_backend = "pgvector"
    # e.g. postgresql://user:pass@localhost:5432/akp
    pg_vector_url: str = ""
    # Embedding dimension must match the chosen model
    # all-MiniLM-L6-v2 → 384, all-mpnet-base-v2 → 768
    embedding_dim: int = 384

    # Embedding model (local, no API key needed)
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_device: str = "cpu"

    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 64

    # Search
    default_top_k: int = 5
    search_score_threshold: float = 0.0  # minimum cosine similarity to return (0 = off)

    # Reranker (cross-encoder, optional — empty string = disabled)
    reranker_model: str = ""

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_key: str = ""

    # JWT
    jwt_secret: str = "change-me-in-production-use-a-random-32-char-string"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def model_post_init(self, __context):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_persist_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
