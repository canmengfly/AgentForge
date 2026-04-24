from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


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
