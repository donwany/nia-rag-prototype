"""Configuration for the nia.gov.gh scraper."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ScraperConfig:
    base_url: str = "https://nia.gov.gh/"
    sitemap_index: str = "https://nia.gov.gh/sitemap_index.xml"
    robots_url: str = "https://nia.gov.gh/robots.txt"

    user_agent: str = (
        "NIA-RAG-Scraper/1.0 (+educational project; contact: info@nia.gov.gh)"
    )
    request_timeout: int = 30
    max_retries: int = 3
    backoff_factor: float = 1.0

    # Politeness: seconds to wait between live requests (cache hits are free).
    request_delay: float = 1.0

    # Safety valves for the link-following fallback crawl.
    max_crawl_depth: int = 3
    max_pages: int = 1000

    data_dir: Path = PROJECT_ROOT / "data"
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"

    markdown_output: Path = PROJECT_ROOT / "data" / "nia_website.md"
    jsonl_output: Path = PROJECT_ROOT / "data" / "pages.jsonl"
    assets_output: Path = PROJECT_ROOT / "data" / "assets.json"

    # A line appearing on more than this fraction of pages is treated as
    # chrome (mega-menu, footer, cookie notice) and dropped.
    boilerplate_threshold: float = 0.6
    # Lines shorter than this are never considered content-bearing on their own
    # when deduping, which keeps short headings from being over-eagerly removed.
    boilerplate_min_length: int = 3

    # URL path prefixes that never carry useful content.
    excluded_prefixes: tuple[str, ...] = (
        "/wp-admin",
        "/wp-login",
        "/wp-json",
        "/feed",
        "/comments",
        "/author/",
        "/tag/",
    )

    # File extensions we record as assets rather than crawl as HTML.
    document_extensions: tuple[str, ...] = (
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".zip",
    )

    media_extensions: tuple[str, ...] = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".mp4",
        ".mp3",
    )

    # Selectors removed before text extraction. Elementor renders the site
    # header/footer as template parts that otherwise repeat on all 463 pages.
    strip_selectors: tuple[str, ...] = field(
        default=(
            "script",
            "style",
            "noscript",
            "iframe",
            "svg",
            "form",
            "header",
            "footer",
            "nav",
            ".elementor-location-header",
            ".elementor-location-footer",
            ".site-header",
            ".site-footer",
            # The Creote theme renders the footer as an ordinary Elementor
            # template inside .footer_area rather than a <footer> element.
            ".footer_area",
            ".main-navigation",
            ".menu-wrapper",
            ".breadcrumb",
            ".breadcrumbs",
            ".cookie-notice",
            ".cookie-banner",
            ".screen-reader-text",
            ".skip-link",
            "#back-to-top",
            ".creote-preloader",
            ".search-popup",
            ".mobile-menu",
            ".offcanvas",
        )
    )

    # Preference order when locating the content root of a page.
    content_selectors: tuple[str, ...] = (
        "div.elementor",
        "main",
        "article",
        "#content",
        ".site-main",
        ".entry-content",
    )


CONFIG = ScraperConfig()
