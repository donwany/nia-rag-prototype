"""Serialisation of scraped pages to markdown, JSONL and an asset manifest."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .parser import PageData

logger = logging.getLogger(__name__)

# Page titles occupy level 2, so body headings start at level 3.
PAGE_HEADING_LEVEL = 2
BODY_HEADING_OFFSET = 2

TYPE_LABELS = {
    "page": "Pages",
    "news": "News and Press Releases",
    "service": "Services",
    "category": "Category Archives",
    "office_location": "Office Locations",
    "discovered": "Additional Pages",
}


def _demote_headings(markdown: str, offset: int = BODY_HEADING_OFFSET) -> str:
    """Shift body headings down so they nest under the page heading."""

    def repl(match: re.Match[str]) -> str:
        level = min(len(match.group(1)) + offset, 6)
        return f"{'#' * level} {match.group(2)}"

    return re.sub(r"^(#{1,6})\s+(.*)$", repl, markdown, flags=re.MULTILINE)


def _anchor(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    return re.sub(r"[\s_]+", "-", slug)


def write_markdown(pages: list[PageData], path: Path) -> None:
    """Write the single-file corpus that the RAG pipeline ingests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by_type = Counter(page.content_type for page in pages)

    out: list[str] = [
        "# National Identification Authority (NIA) - Website Corpus",
        "",
        "Scraped from <https://nia.gov.gh/> for a Retrieval-Augmented Generation system.",
        "",
        f"- **Source:** https://nia.gov.gh/",
        f"- **Generated:** {generated}",
        f"- **Pages:** {len(pages)}",
        f"- **Total words:** {sum(p.word_count for p in pages):,}",
        "",
        "| Content type | Pages |",
        "| --- | --- |",
    ]
    for content_type, count in by_type.most_common():
        out.append(f"| {TYPE_LABELS.get(content_type, content_type)} | {count} |")

    out += ["", "---", "", "## Contents", ""]
    grouped: dict[str, list[PageData]] = {}
    for page in pages:
        grouped.setdefault(page.content_type, []).append(page)
    for content_type in sorted(grouped, key=lambda t: -len(grouped[t])):
        out.append(f"**{TYPE_LABELS.get(content_type, content_type)}**")
        out.append("")
        for page in grouped[content_type]:
            out.append(f"- [{page.title}](#{_anchor(page.title)})")
        out.append("")

    for page in pages:
        out += ["", "---", "", f"{'#' * PAGE_HEADING_LEVEL} {page.title}", ""]
        out.append(f"- **URL:** {page.url}")
        out.append(f"- **Content type:** {page.content_type}")
        if page.description:
            out.append(f"- **Summary:** {page.description}")
        if page.published:
            out.append(f"- **Published:** {page.published}")
        if page.lastmod:
            out.append(f"- **Last modified:** {page.lastmod}")
        out.append(f"- **Word count:** {page.word_count}")
        out += ["", _demote_headings(page.markdown), ""]

        if page.documents:
            out += ["**Documents linked from this page:**", ""]
            out += [
                f"- [{doc['text'] or doc['url'].rsplit('/', 1)[-1]}]({doc['url']})"
                for doc in page.documents
            ]
            out.append("")

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    logger.info("Wrote %s (%.1f KB)", path, path.stat().st_size / 1024)


def write_jsonl(pages: list[PageData], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for page in pages:
            handle.write(json.dumps(page.to_dict(), ensure_ascii=False) + "\n")
    logger.info("Wrote %s (%d records)", path, len(pages))


def write_assets(pages: list[PageData], path: Path) -> None:
    """Aggregate every image, document, media file and outbound link."""
    images: dict[str, dict] = {}
    documents: dict[str, dict] = {}
    media: dict[str, dict] = {}
    external_links: dict[str, dict] = {}

    for page in pages:
        for image in page.images:
            entry = images.setdefault(
                image["src"], {"src": image["src"], "alt": image.get("alt", ""), "pages": []}
            )
            entry["pages"].append(page.url)
        for doc in page.documents:
            entry = documents.setdefault(
                doc["url"], {"url": doc["url"], "text": doc.get("text", ""), "pages": []}
            )
            entry["pages"].append(page.url)
        for item in page.media:
            entry = media.setdefault(
                item["src"], {"src": item["src"], "type": item.get("type", ""), "pages": []}
            )
            entry["pages"].append(page.url)
        for link in page.links:
            if link.get("internal"):
                continue
            entry = external_links.setdefault(
                link["url"], {"url": link["url"], "text": link.get("text", ""), "pages": []}
            )
            entry["pages"].append(page.url)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "https://nia.gov.gh/",
        "counts": {
            "images": len(images),
            "documents": len(documents),
            "media": len(media),
            "external_links": len(external_links),
        },
        "images": sorted(images.values(), key=lambda a: a["src"]),
        "documents": sorted(documents.values(), key=lambda a: a["url"]),
        "media": sorted(media.values(), key=lambda a: a["src"]),
        "external_links": sorted(external_links.values(), key=lambda a: a["url"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "Wrote %s (%d images, %d documents, %d media, %d external links)",
        path,
        len(images),
        len(documents),
        len(media),
        len(external_links),
    )
