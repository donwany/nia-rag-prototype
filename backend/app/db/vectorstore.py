"""PGVector-backed vector store and OpenAI embeddings."""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from ..config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_embeddings(config: Settings = default_settings) -> OpenAIEmbeddings:
    if not config.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set; cannot create embeddings")
    return OpenAIEmbeddings(
        model=config.openai_embedding_model,
        api_key=config.openai_api_key,
        # Batch size keeps request payloads well under the token limit while
        # still amortising HTTP overhead across the corpus.
        chunk_size=256,
    )


def build_vector_store(
    config: Settings = default_settings, pre_delete_collection: bool = False
) -> PGVector:
    """Create a PGVector handle, provisioning the extension and tables."""
    return PGVector(
        embeddings=get_embeddings(config),
        collection_name=config.pgvector_collection,
        connection=config.postgres_dsn,
        use_jsonb=True,
        create_extension=True,
        pre_delete_collection=pre_delete_collection,
    )


@lru_cache
def get_vector_store(config: Settings = default_settings) -> PGVector:
    """Process-wide singleton used by the API at request time."""
    store = build_vector_store(config)
    logger.info(
        "Connected to PGVector collection '%s' on %s:%s",
        config.pgvector_collection,
        config.postgres_host,
        config.postgres_port,
    )
    return store


def count_documents(config: Settings = default_settings) -> int:
    """Rows currently embedded, used by the health endpoint."""
    import sqlalchemy

    engine = sqlalchemy.create_engine(config.postgres_dsn)
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                sqlalchemy.text("SELECT to_regclass('public.langchain_pg_embedding')")
            ).scalar()
            if not exists:
                return 0
            return connection.execute(
                sqlalchemy.text("SELECT count(*) FROM langchain_pg_embedding")
            ).scalar_one()
    finally:
        engine.dispose()
