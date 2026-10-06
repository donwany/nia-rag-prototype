"""Turn scraped pages into embedding-ready LangChain documents.

Two splitting strategies run side by side:

* Ordinary pages are split on markdown headers first so chunks inherit their
  section context, then packed to a character budget with overlap.
* Office locations bypass splitting entirely. There are 307 of them and they
  are short and near-identical in shape, so keeping one record per chunk means
  a location question retrieves one complete, unambiguous answer instead of
  fragments stitched from neighbouring offices.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from ..config import Settings, settings as default_settings

logger = logging.getLogger(__name__)

HEADERS_TO_SPLIT_ON = [("#", "h1"), ("##", "h2"), ("###", "h3")]

TABLE_LINE = re.compile(r"^\s*\|")
TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
# A row whose trailing cells are all empty is a group heading inside the table
# (for example "| ##### 2. Card Replacement Service | | |").
TABLE_GROUP_ROW = re.compile(r"^\s*\|([^|]+)\|(\s*\|)*\s*$")

# Content types kept whole rather than split.
ATOMIC_CONTENT_TYPES = {"office_location"}

# Chunks shorter than this carry no usable signal.
MIN_CHUNK_CHARS = 80


def load_pages(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m scraper.run_scrape` first."
        )
    pages: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                pages.append(json.loads(line))
    logger.info("Loaded %d pages from %s", len(pages), path)
    return pages


def content_hash(url: str, text: str) -> str:
    return hashlib.sha256(f"{url}\n{text}".encode("utf-8")).hexdigest()


def _base_metadata(page: dict) -> dict:
    return {
        "source_url": page.get("url", ""),
        "title": page.get("title", ""),
        "content_type": page.get("content_type", "page"),
        "scraped_at": page.get("scraped_at", ""),
        "published": page.get("published") or "",
        "lastmod": page.get("lastmod") or "",
    }


def _section_label(header_metadata: dict, fallback: str) -> str:
    for key in ("h3", "h2", "h1"):
        value = header_metadata.get(key)
        if value:
            return _plain_text(value)
    return fallback


def _plain_text(value: str) -> str:
    """Strip markdown emphasis and link syntax out of a heading."""
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[*_`]+", "", value)
    return value.strip()


def _segment_blocks(text: str) -> list[tuple[str, str]]:
    """Split text into consecutive ``("table" | "text", block)`` segments."""
    segments: list[tuple[str, str]] = []
    buffer: list[str] = []
    mode = "text"

    for line in text.splitlines():
        kind = "table" if TABLE_LINE.match(line) else "text"
        if kind != mode and buffer:
            segments.append((mode, "\n".join(buffer)))
            buffer = []
        mode = kind
        buffer.append(line)

    if buffer:
        segments.append((mode, "\n".join(buffer)))
    return segments


def _split_table(table: str, chunk_size: int) -> list[str]:
    """Split a markdown table on row boundaries, repeating its headers.

    Character-based splitting cuts tables mid-row and leaves later pieces as
    bare cells with no column names, which is unreadable for the generator and
    nearly unmatchable for the embedder. Every piece therefore carries the
    header row, the separator, and the most recent in-table group heading.
    """
    lines = [line for line in table.splitlines() if line.strip()]
    if len(lines) < 2:
        return [table]

    header = [lines[0]]
    body_start = 1
    if TABLE_SEPARATOR.match(lines[1]):
        header.append(lines[1])
        body_start = 2

    header_size = sum(len(line) + 1 for line in header)
    chunks: list[str] = []
    current: list[str] = []
    group_row: str | None = None
    size = header_size

    for row in lines[body_start:]:
        is_group = bool(TABLE_GROUP_ROW.match(row))

        # Start a new chunk at each group heading. A fee category is the unit
        # a question is actually about, so keeping "Card Replacement Service"
        # whole beats packing it in behind unrelated registration rows that
        # would otherwise dominate the chunk's embedding.
        if is_group and current and any(
            not TABLE_GROUP_ROW.match(line) for line in current
        ):
            chunks.append("\n".join(header + current))
            current = []
            size = header_size

        if current and size + len(row) + 1 > chunk_size:
            chunks.append("\n".join(header + current))
            current = []
            size = header_size
            # Carry the group heading into the continuation so rows keep the
            # section they belong to.
            if group_row and not is_group:
                current.append(group_row)
                size += len(group_row) + 1

        current.append(row)
        size += len(row) + 1
        if is_group:
            group_row = row

    if current:
        chunks.append("\n".join(header + current))
    return chunks or [table]


def _split_content(text: str, splitter: RecursiveCharacterTextSplitter, chunk_size: int) -> list[str]:
    """Split a section, routing tables through the table-aware splitter."""
    pieces: list[str] = []
    for kind, block in _segment_blocks(text):
        if not block.strip():
            continue
        if kind == "table":
            pieces.extend(_split_table(block, chunk_size))
        else:
            pieces.extend(splitter.split_text(block))
    return pieces


def _contextualise(page: dict, section: str, text: str) -> str:
    """Prefix each chunk with its page title and section.

    Retrieval happens on the embedding of the chunk alone, so a chunk lifted
    out of the middle of a page needs to carry enough context to be matchable
    and to read sensibly when handed to the generator.
    """
    title = page.get("title", "").strip()
    header = title
    if section and section.strip() and section.strip().lower() != title.lower():
        header = f"{title} - {section.strip()}"
    return f"# {header}\n\n{text.strip()}" if header else text.strip()


def chunk_page(page: dict, config: Settings = default_settings) -> list[Document]:
    markdown = (page.get("markdown") or "").strip()
    if not markdown:
        return []

    metadata = _base_metadata(page)
    url = metadata["source_url"]

    if metadata["content_type"] in ATOMIC_CONTENT_TYPES:
        text = _contextualise(page, "", markdown)
        return [
            Document(
                page_content=text,
                metadata={
                    **metadata,
                    "section": metadata["title"],
                    "chunk_index": 0,
                    "content_hash": content_hash(url, text),
                },
            )
        ]

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=HEADERS_TO_SPLIT_ON, strip_headers=False
    )
    character_splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )

    try:
        sections = header_splitter.split_text(markdown)
    except Exception as exc:  # malformed markdown shouldn't lose a page
        logger.debug("Header split failed for %s (%s); falling back", url, exc)
        sections = [Document(page_content=markdown, metadata={})]

    documents: list[Document] = []
    for section in sections:
        label = _section_label(section.metadata, metadata["title"])
        for piece in _split_content(
            section.page_content, character_splitter, config.chunk_size
        ):
            piece = piece.strip()
            if len(piece) < MIN_CHUNK_CHARS:
                continue
            text = _contextualise(page, label, piece)
            documents.append(
                Document(
                    page_content=text,
                    metadata={
                        **metadata,
                        "section": label,
                        "chunk_index": len(documents),
                        "content_hash": content_hash(url, text),
                    },
                )
            )

    # A page whose body is one short blob yields nothing above; keep it anyway.
    if not documents and len(markdown) >= MIN_CHUNK_CHARS:
        text = _contextualise(page, "", markdown)
        documents.append(
            Document(
                page_content=text,
                metadata={
                    **metadata,
                    "section": metadata["title"],
                    "chunk_index": 0,
                    "content_hash": content_hash(url, text),
                },
            )
        )
    return documents


def chunk_pages(pages: list[dict], config: Settings = default_settings) -> list[Document]:
    documents: list[Document] = []
    seen_hashes: set[str] = set()

    for page in pages:
        for document in chunk_page(page, config):
            digest = document.metadata["content_hash"]
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            documents.append(document)

    logger.info("Produced %d unique chunks from %d pages", len(documents), len(pages))
    return documents
