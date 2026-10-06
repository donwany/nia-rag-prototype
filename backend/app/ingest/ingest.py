"""Embed the scraped corpus into PGVector.

    python -m app.ingest.ingest --source ../data/pages.jsonl
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from langchain_core.documents import Document

from ..config import settings
from ..db.vectorstore import build_vector_store
from .chunker import chunk_pages, load_pages

logger = logging.getLogger("ingest")

DEFAULT_BATCH_SIZE = 100


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest the NIA corpus into PGVector")
    parser.add_argument(
        "--source",
        type=Path,
        default=settings.pages_jsonl,
        help="Path to pages.jsonl produced by the scraper",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop the existing collection before ingesting",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chunk and report without calling OpenAI or writing to Postgres",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def summarise(documents: list[Document]) -> None:
    by_type = Counter(d.metadata.get("content_type", "unknown") for d in documents)
    lengths = [len(d.page_content) for d in documents]
    logger.info("Chunks by content type: %s", dict(by_type))
    if lengths:
        logger.info(
            "Chunk characters: min=%d median=%d max=%d mean=%d",
            min(lengths),
            sorted(lengths)[len(lengths) // 2],
            max(lengths),
            sum(lengths) // len(lengths),
        )


def ingest(documents: list[Document], reset: bool, batch_size: int) -> int:
    store = build_vector_store(settings, pre_delete_collection=reset)
    if reset:
        logger.info("Collection '%s' reset", settings.pgvector_collection)

    written = 0
    total = len(documents)
    for start in range(0, total, batch_size):
        batch = documents[start : start + batch_size]
        # Using the content hash as the primary key makes re-ingestion
        # idempotent: unchanged chunks overwrite themselves instead of
        # accumulating duplicates.
        ids = [doc.metadata["content_hash"] for doc in batch]
        store.add_documents(batch, ids=ids)
        written += len(batch)
        logger.info("Embedded %d/%d chunks", written, total)
    return written


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    started = time.monotonic()
    try:
        pages = load_pages(args.source)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1

    documents = chunk_pages(pages, settings)
    summarise(documents)

    if not documents:
        logger.error("Nothing to ingest")
        return 1

    if args.dry_run:
        logger.info("Dry run: skipping embedding and database write")
        for doc in documents[:3]:
            logger.info(
                "--- %s (%s)\n%s",
                doc.metadata["title"],
                doc.metadata["section"],
                doc.page_content[:300],
            )
        return 0

    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is not set; cannot embed")
        return 1

    written = ingest(documents, reset=args.reset, batch_size=args.batch_size)
    logger.info(
        "Ingested %d chunks into '%s' in %.1fs",
        written,
        settings.pgvector_collection,
        time.monotonic() - started,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
