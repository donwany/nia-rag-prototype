"""Scraper for https://nia.gov.gh/ feeding the NIA RAG corpus."""

from .config import CONFIG, ScraperConfig
from .crawler import Crawler, SeedUrl, build_session, normalize_url
from .parser import PageData, PageParser, normalize_text

__all__ = [
    "CONFIG",
    "ScraperConfig",
    "Crawler",
    "SeedUrl",
    "build_session",
    "normalize_url",
    "PageData",
    "PageParser",
    "normalize_text",
]
