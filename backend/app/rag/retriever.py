"""Retrieval helpers over the PGVector collection."""

from __future__ import annotations

import asyncio
import logging

from langchain_core.documents import Document

from ..config import Settings, settings as default_settings
from ..db.vectorstore import get_vector_store

logger = logging.getLogger(__name__)

# Cosine distance above which a hit is treated as noise. PGVector returns
# distance (0 = identical), so smaller is better.
MAX_DISTANCE = 0.75


class RetrievalError(RuntimeError):
    """Retrieval could not run at all (database or embedding API failure).

    Distinct from retrieving nothing: an empty result is a legitimate answer
    about the corpus, whereas this means the question was never really asked.
    Collapsing the two would report a misconfigured API key as "I don't know".
    """


async def retrieve(
    query: str,
    config: Settings = default_settings,
    k: int | None = None,
    content_type: str | None = None,
) -> list[Document]:
    """Similarity search, run off the event loop since PGVector is synchronous."""
    k = k or config.retriever_k
    filter_ = {"content_type": {"$eq": content_type}} if content_type else None

    def _search() -> list[tuple[Document, float]]:
        store = get_vector_store(config)
        return store.similarity_search_with_score(query, k=k, filter=filter_)

    try:
        results = await asyncio.to_thread(_search)
    except Exception as exc:
        logger.exception("Vector search failed for %r: %s", query, exc)
        raise RetrievalError(str(exc)) from exc

    documents: list[Document] = []
    for document, distance in results:
        if distance > MAX_DISTANCE:
            continue
        document.metadata["score"] = round(1.0 - float(distance), 4)
        documents.append(document)

    logger.debug("Retrieved %d/%d documents for %r", len(documents), len(results), query)
    return documents


def format_context(documents: list[Document]) -> str:
    """Render documents as the numbered context block the answer prompt expects."""
    blocks: list[str] = []
    for index, document in enumerate(documents, start=1):
        title = document.metadata.get("title", "Untitled")
        url = document.metadata.get("source_url", "")
        blocks.append(f"[{index}] {title}\nSource: {url}\n\n{document.page_content}")
    return "\n\n---\n\n".join(blocks)


def format_sources(documents: list[Document]) -> list[dict]:
    """Deduplicate documents by URL for display in the UI sources panel."""
    sources: list[dict] = []
    seen: set[str] = set()
    for index, document in enumerate(documents, start=1):
        url = document.metadata.get("source_url", "")
        if url in seen:
            continue
        seen.add(url)
        sources.append(
            {
                "index": index,
                "title": document.metadata.get("title", "Untitled"),
                "url": url,
                "section": document.metadata.get("section", ""),
                "content_type": document.metadata.get("content_type", ""),
                "score": document.metadata.get("score", 0.0),
                "snippet": document.page_content[:280].strip(),
            }
        )
    return sources
