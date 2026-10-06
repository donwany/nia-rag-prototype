"""HTML parsing and markdown rendering for nia.gov.gh pages.

The site is built with Elementor, which emits deeply nested ``div`` soup with
no ``<main>`` or ``<article>`` landmarks. Content is therefore located by
stripping the known chrome (header/footer template parts) and then rendering
the remaining Elementor container into markdown with a small recursive
renderer, which preserves headings, lists and tables far better than
``get_text()`` would.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, CData, Comment, Doctype, NavigableString, Tag
from bs4.element import ProcessingInstruction

from .config import CONFIG, ScraperConfig

logger = logging.getLogger(__name__)

HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
INLINE_SKIP = {"script", "style", "noscript", "svg", "iframe", "template"}

# Comments and friends subclass NavigableString, so they must be filtered
# explicitly or Elementor's editor annotations leak into the markdown.
NON_TEXT_STRINGS = (Comment, CData, Doctype, ProcessingInstruction)


@dataclass
class PageData:
    url: str
    title: str
    content_type: str
    description: str = ""
    canonical: str = ""
    lastmod: str | None = None
    published: str | None = None
    markdown: str = ""
    headings: list[str] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    documents: list[dict[str, str]] = field(default_factory=list)
    media: list[dict[str, str]] = field(default_factory=list)
    word_count: int = 0
    scraped_at: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "content_type": self.content_type,
            "description": self.description,
            "canonical": self.canonical,
            "lastmod": self.lastmod,
            "published": self.published,
            "markdown": self.markdown,
            "headings": self.headings,
            "images": self.images,
            "links": self.links,
            "documents": self.documents,
            "media": self.media,
            "word_count": self.word_count,
            "scraped_at": self.scraped_at,
        }


def normalize_text(text: str) -> str:
    """NFKC-normalise, repair hyphenation, and collapse runaway whitespace.

    Deliberately preserves case and punctuation: transformer embedding models
    are trained on natural text, so lowercasing and stripping punctuation
    (a bag-of-words era habit) measurably degrades retrieval quality.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    # Join words split across a line break by a hyphen.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return text.strip()


class MarkdownRenderer:
    """Recursive HTML -> markdown renderer scoped to the tags this site uses."""

    def __init__(self, page_url: str) -> None:
        self.page_url = page_url

    def render(self, node: Tag) -> str:
        return self._collapse(self._render_node(node, depth=0))

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _collapse(text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _inline(self, node: Tag) -> str:
        """Render children without block separators (for headings, cells, links)."""
        parts = [self._render_node(child, depth=0, inline=True) for child in node.children]
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def _absolute(self, url: str) -> str:
        if not url:
            return ""
        return urljoin(self.page_url, url.strip())

    # -- dispatch ----------------------------------------------------------

    def _render_node(self, node, depth: int, inline: bool = False) -> str:
        if isinstance(node, NON_TEXT_STRINGS):
            return ""
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()
        if name in INLINE_SKIP:
            return ""

        if name in HEADING_TAGS:
            text = self._inline(node)
            if not text:
                return ""
            level = HEADING_TAGS[name]
            return f"\n\n{'#' * level} {text}\n\n"

        if name == "p":
            text = self._children(node, depth)
            return f"\n\n{text.strip()}\n\n" if text.strip() else ""

        if name == "br":
            return "\n"

        if name == "hr":
            return "\n\n---\n\n"

        if name in ("ul", "ol"):
            return self._render_list(node, depth)

        if name == "table":
            return self._render_table(node)

        if name == "a":
            return self._render_anchor(node)

        if name == "img":
            return self._render_image(node)

        if name in ("strong", "b"):
            text = self._inline(node)
            return f"**{text}**" if text else ""

        if name in ("em", "i"):
            text = self._inline(node)
            return f"*{text}*" if text else ""

        if name == "blockquote":
            text = self._children(node, depth).strip()
            if not text:
                return ""
            quoted = "\n".join(f"> {line}" for line in text.splitlines())
            return f"\n\n{quoted}\n\n"

        if name in ("pre", "code"):
            text = node.get_text()
            if not text.strip():
                return ""
            if name == "code" and "\n" not in text:
                return f"`{text.strip()}`"
            return f"\n\n```\n{text.strip()}\n```\n\n"

        # Generic container: recurse, adding a soft block break for block-level
        # elements so Elementor's nested divs don't run together.
        text = self._children(node, depth)
        if name in ("div", "section", "li", "td", "th", "tr", "figure", "figcaption"):
            return text if inline else f"\n{text}\n"
        return text

    def _children(self, node: Tag, depth: int) -> str:
        return "".join(self._render_node(child, depth) for child in node.children)

    def _render_list(self, node: Tag, depth: int) -> str:
        ordered = node.name.lower() == "ol"
        indent = "  " * depth
        lines: list[str] = []
        index = 1
        for item in node.find_all("li", recursive=False):
            nested = []
            for sub in item.find_all(["ul", "ol"], recursive=False):
                nested.append(self._render_list(sub, depth + 1))
                sub.extract()
            text = self._inline(item)
            if text:
                bullet = f"{index}." if ordered else "-"
                lines.append(f"{indent}{bullet} {text}")
                index += 1
            lines.extend(n.strip("\n") for n in nested if n.strip())
        if not lines:
            return ""
        return "\n\n" + "\n".join(lines) + "\n\n"

    def _render_table(self, node: Tag) -> str:
        rows: list[list[str]] = []
        for tr in node.find_all("tr"):
            cells = [self._inline(cell) for cell in tr.find_all(["th", "td"], recursive=False)]
            if any(cell for cell in cells):
                rows.append(cells)
        if not rows:
            return ""

        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        header, *body = rows
        out = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
        out.extend("| " + " | ".join(r) + " |" for r in body)
        return "\n\n" + "\n".join(out) + "\n\n"

    def _render_anchor(self, node: Tag) -> str:
        text = self._inline(node)
        href = self._absolute(node.get("href", ""))
        if not text:
            return ""
        if not href or href.startswith("javascript:"):
            return text
        return f"[{text}]({href})"

    def _render_image(self, node: Tag) -> str:
        src = (
            node.get("src")
            or node.get("data-src")
            or node.get("data-lazy-src")
            or node.get("data-large_image")
            or ""
        )
        src = self._absolute(src)
        if not src or src.startswith("data:"):
            return ""
        alt = (node.get("alt") or "").strip()
        return f"\n\n![{alt}]({src})\n\n"


class PageParser:
    def __init__(self, config: ScraperConfig = CONFIG) -> None:
        self.config = config

    def parse(
        self,
        url: str,
        html: str,
        content_type: str = "page",
        lastmod: str | None = None,
    ) -> PageData | None:
        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup)
        description = self._extract_meta(soup, "description")
        canonical = self._extract_canonical(soup, url)
        published = self._extract_published(soup)

        # Asset harvesting happens on the full document (minus scripts) so we
        # still record media that lives outside the main content container.
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()
        images, links, documents, media = self._extract_assets(soup, url)

        for selector in self.config.strip_selectors:
            for tag in soup.select(selector):
                tag.decompose()

        content_root = self._find_content_root(soup)
        if content_root is None:
            logger.debug("No content root for %s", url)
            return None

        markdown = MarkdownRenderer(url).render(content_root)
        markdown = normalize_text(markdown)
        headings = [
            normalize_text(h.get_text(" ", strip=True))
            for h in content_root.find_all(list(HEADING_TAGS))
            if h.get_text(strip=True)
        ]

        return PageData(
            url=url,
            title=title,
            content_type=content_type,
            description=description,
            canonical=canonical,
            lastmod=lastmod,
            published=published,
            markdown=markdown,
            headings=headings,
            images=images,
            links=links,
            documents=documents,
            media=media,
            word_count=len(markdown.split()),
            scraped_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    # -- metadata ----------------------------------------------------------

    def _extract_title(self, soup: BeautifulSoup) -> str:
        for getter in (
            lambda: soup.find("meta", property="og:title"),
            lambda: soup.find("title"),
        ):
            tag = getter()
            if tag is None:
                continue
            raw = tag.get("content") if tag.name == "meta" else tag.get_text()
            if raw and raw.strip():
                # Rank Math appends the site name to every title.
                cleaned = re.split(r"\s*[|-]\s*National Identification Authority", raw)[0]
                return normalize_text(cleaned) or normalize_text(raw)
        h1 = soup.find("h1")
        return normalize_text(h1.get_text()) if h1 else "Untitled"

    @staticmethod
    def _extract_meta(soup: BeautifulSoup, name: str) -> str:
        tag = soup.find("meta", attrs={"name": name}) or soup.find(
            "meta", property=f"og:{name}"
        )
        if tag and tag.get("content"):
            return normalize_text(tag["content"])
        return ""

    @staticmethod
    def _extract_canonical(soup: BeautifulSoup, fallback: str) -> str:
        tag = soup.find("link", rel="canonical")
        if tag and tag.get("href"):
            return tag["href"].strip()
        return fallback

    @staticmethod
    def _extract_published(soup: BeautifulSoup) -> str | None:
        tag = soup.find("meta", property="article:published_time")
        if tag and tag.get("content"):
            return tag["content"].strip()
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            return time_tag["datetime"].strip()
        return None

    def _find_content_root(self, soup: BeautifulSoup) -> Tag | None:
        """Locate the container holding this page's own content.

        WordPress stamps the current object's ID onto the body element
        (``page-id-6445``, ``postid-1234``), and Elementor stamps the same ID
        onto the matching content wrapper. Pairing the two picks out the page
        body exactly, leaving the shared header and footer templates behind --
        which matters because those templates carry more text than a sparse
        page does, so a "largest container" heuristic alone picks the footer.
        """
        root = self._root_by_object_id(soup)
        if root is not None:
            return root

        for selector in self.config.content_selectors:
            candidates = soup.select(selector)
            if not candidates:
                continue
            best = max(candidates, key=lambda c: len(c.get_text(strip=True)))
            if len(best.get_text(strip=True)) > 100:
                return best
        return soup.body or soup

    @staticmethod
    def _root_by_object_id(soup: BeautifulSoup) -> Tag | None:
        body = soup.body
        if body is None:
            return None
        classes = " ".join(body.get("class") or [])
        match = re.search(r"\b(?:page-id|postid|post-id)-(\d+)\b", classes)
        if not match:
            return None
        return soup.select_one(f'div.elementor[data-elementor-id="{match.group(1)}"]')

    def _extract_assets(
        self, soup: BeautifulSoup, page_url: str
    ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        host = urlparse(page_url).netloc.lower()
        images: list[dict] = []
        links: list[dict] = []
        documents: list[dict] = []
        media: list[dict] = []
        seen_images: set[str] = set()
        seen_links: set[str] = set()

        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if not src or src.startswith("data:"):
                continue
            absolute = urljoin(page_url, src.strip())
            if absolute in seen_images:
                continue
            seen_images.add(absolute)
            images.append({"src": absolute, "alt": (img.get("alt") or "").strip()})

        for source in soup.find_all(["video", "audio", "source"]):
            src = source.get("src")
            if src:
                media.append(
                    {"src": urljoin(page_url, src.strip()), "type": source.name}
                )

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.startswith(("javascript:", "#")):
                continue
            absolute = urljoin(page_url, href)
            if absolute in seen_links:
                continue
            seen_links.add(absolute)
            text = normalize_text(anchor.get_text(" ", strip=True))
            suffix = Path(urlparse(absolute).path).suffix.lower()
            entry = {"url": absolute, "text": text}
            if suffix in self.config.document_extensions:
                documents.append(entry)
            elif suffix in self.config.media_extensions:
                media.append({"src": absolute, "type": "link"})
            else:
                entry["internal"] = urlparse(absolute).netloc.lower() == host
                links.append(entry)

        return images, links, documents, media
