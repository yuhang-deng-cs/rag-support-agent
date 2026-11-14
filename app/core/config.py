"""Application settings, loaded from environment variables / `.env`."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"  # noqa: S105 - explicit dev placeholder


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # --- Database -----------------------------------------------------------
    # SQLite works out of the box; use PostgreSQL + pgvector for RLS enforcement.
    database_url: str = "sqlite+aiosqlite:///./rag_local.db"

    # --- Auth ---------------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_ttl_minutes: int = Field(default=60, ge=1)
    allow_public_signup: bool = True
    invite_ttl_hours: int = Field(default=72, ge=1)

    # --- Embeddings ---------------------------------------------------------
    # "fastembed": local ONNX model, no API key (pip install ".[local]")
    # "openai":    any OpenAI-compatible /embeddings endpoint (OpenAI, Ollama, vLLM, ...)
    # "hash":      deterministic lexical hashing - for tests/CI only, not semantic
    embedding_provider: Literal["fastembed", "openai", "hash"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = Field(default=384, ge=8)
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""

    # --- LLM ----------------------------------------------------------------
    # "extractive": offline, answers with the most relevant cited sentences
    # "openai":     any OpenAI-compatible /chat/completions endpoint
    llm_provider: Literal["extractive", "openai"] = "extractive"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0

    # --- Retrieval ----------------------------------------------------------
    retrieval_top_k: int = Field(default=4, ge=1, le=20)
    # Cosine-similarity floor below which the agent abstains. 0.6 is calibrated for
    # bge-small-en-v1.5 on the sample docs (on-topic >= 0.73, off-topic <= 0.57);
    # re-calibrate with `python scripts/eval.py` when you change the embedding model.
    retrieval_min_score: float = Field(default=0.6, ge=-1.0, le=1.0)
    context_pruning: bool = True
    chunk_size: int = Field(default=800, ge=100)
    chunk_overlap: int = Field(default=120, ge=0)

    # --- Ingestion ----------------------------------------------------------
    # "inline": run in the API process after the response (no Redis needed)
    # "celery": enqueue to a Celery worker (pip install ".[celery]")
    ingestion_backend: Literal["inline", "celery"] = "inline"
    redis_url: str = "redis://localhost:6379/0"
    max_upload_mb: int = Field(default=10, ge=1)

    # --- Demo ---------------------------------------------------------------
    seed_demo: bool = False
    cors_origins: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.app_env == "production":
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("Set JWT_SECRET to a random string of 32+ chars in production")
            if self.seed_demo:
                raise ValueError("SEED_DEMO must be disabled in production")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
