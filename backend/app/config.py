"""Application settings, loaded from the environment / project-root .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Frozen makes the model hashable, which @lru_cache requires of any
        # argument. Settings are read-only after startup anyway.
        frozen=True,
    )

    app_name: str = "NIA RAG API"
    api_prefix: str = "/api"
    debug: bool = False

    # OpenAI -----------------------------------------------------------------
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_chat_model: str = Field(default="gpt-4o-mini", alias="OPENAI_CHAT_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )
    llm_temperature: float = 0.0

    # Postgres / PGVector ----------------------------------------------------
    postgres_user: str = Field(default="nia", alias="POSTGRES_USER")
    postgres_password: str = Field(default="nia_password", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="nia_rag", alias="POSTGRES_DB")
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    pgvector_collection: str = Field(default="nia_documents", alias="PGVECTOR_COLLECTION")

    # MongoDB ----------------------------------------------------------------
    mongodb_uri: str = Field(
        default="mongodb://nia:nia_password@mongo:27017", alias="MONGODB_URI"
    )
    mongodb_db: str = Field(default="nia_rag", alias="MONGODB_DB")

    # Auth -------------------------------------------------------------------
    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    # Retrieval --------------------------------------------------------------
    retriever_k: int = Field(default=6, alias="RETRIEVER_K")
    retriever_fetch_k: int = 20
    max_query_rewrites: int = Field(default=1, alias="MAX_QUERY_REWRITES")
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # HTTP -------------------------------------------------------------------
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000", alias="CORS_ORIGINS"
    )

    # Data -------------------------------------------------------------------
    # Overridable because the container layout differs from the repo layout:
    # the image copies app/ and scraper/ to /srv and mounts the corpus at /data.
    data_dir: Path = Field(default=PROJECT_ROOT / "data", alias="DATA_DIR")

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def postgres_dsn(self) -> str:
        """SQLAlchemy-style DSN used by langchain_postgres."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def pages_jsonl(self) -> Path:
        return self.data_dir / "pages.jsonl"

    @property
    def corpus_markdown(self) -> Path:
        return self.data_dir / "nia_website.md"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
