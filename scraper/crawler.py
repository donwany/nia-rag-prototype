"""Polite HTTP fetching and URL discovery for nia.gov.gh.

Discovery is sitemap-first because the site publishes a Rank Math sitemap
index covering posts, pages, services, categories and office locations. A
breadth-first link crawl runs afterwards to catch anything the sitemap misses.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import CONFIG, ScraperConfig

logger = logging.getLogger(__name__)

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Maps the Rank Math child sitemap name onto the content type we carry through
# to chunk metadata, so the retriever can filter on it later.
SITEMAP_CONTENT_TYPES = {
    "post": "news",
    "page": "page",
    "service": "service",
    "category": "category",
    "office-locations": "office_location",
}


@dataclass
class SeedUrl:
    url: str
    content_type: str
    lastmod: str | None = None


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    html: str | None
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.html is not None and 200 <= self.status_code < 300


def build_session(config: ScraperConfig = CONFIG) -> requests.Session:
    """A session with bounded retries on transient failures."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    retry = Retry(
        total=config.max_retries,
        backoff_factor=config.backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class RobotsPolicy:
    """Thin wrapper around RobotFileParser that fails open on fetch errors."""

    def __init__(self, config: ScraperConfig = CONFIG) -> None:
        self._config = config
        self._parser = RobotFileParser()
        self._loaded = False

    def load(self, session: requests.Session) -> None:
        try:
            response = session.get(
                self._config.robots_url, timeout=self._config.request_timeout
            )
            response.raise_for_status()
            self._parser.parse(response.text.splitlines())
            self._loaded = True
            logger.info("Loaded robots.txt from %s", self._config.robots_url)
        except requests.RequestException as exc:
            logger.warning("Could not load robots.txt (%s); proceeding politely", exc)

    def allows(self, url: str) -> bool:
        if not self._loaded:
            return True
        return self._parser.can_fetch(self._config.user_agent, url)


def normalize_url(url: str, base: str | None = None) -> str:
    """Absolutise, drop the fragment, and settle on a single trailing-slash form."""
    if base:
        url = urljoin(base, url)
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    # Strip query strings: on this WordPress site they only produce duplicates
    # of pages we already have (pagination params, Elementor preview tokens).
    path = parsed.path or "/"
    if not path.endswith("/") and not Path(path).suffix:
        path = f"{path}/"
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"


class Crawler:
    def __init__(
        self,
        config: ScraperConfig = CONFIG,
        session: requests.Session | None = None,
        use_cache: bool = True,
    ) -> None:
        self.config = config
        self.session = session or build_session(config)
        self.use_cache = use_cache
        self.robots = RobotsPolicy(config)
        self.robots.load(self.session)
        self._last_request_at = 0.0
        self._host = urlparse(config.base_url).netloc.lower()
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- caching -----------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.config.cache_dir / f"{digest}.html"

    def _read_cache(self, url: str) -> str | None:
        if not self.use_cache:
            return None
        path = self._cache_path(url)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
        return None

    def _write_cache(self, url: str, html: str) -> None:
        if self.use_cache:
            self._cache_path(url).write_text(html, encoding="utf-8")

    # -- fetching ----------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.config.request_delay:
            time.sleep(self.config.request_delay - elapsed)
        self._last_request_at = time.monotonic()

    def fetch(self, url: str) -> FetchResult:
        cached = self._read_cache(url)
        if cached is not None:
            return FetchResult(url, url, 200, cached, from_cache=True)

        if not self.robots.allows(url):
            logger.info("robots.txt disallows %s", url)
            return FetchResult(url, url, 403, None)

        self._throttle()
        try:
            response = self.session.get(
                url, timeout=self.config.request_timeout, allow_redirects=True
            )
        except requests.RequestException as exc:
            logger.warning("Request failed for %s: %s", url, exc)
            return FetchResult(url, url, 0, None)

        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            logger.debug("Skipping non-HTML response (%s) at %s", content_type, url)
            return FetchResult(url, response.url, response.status_code, None)

        if not response.ok:
            logger.warning("HTTP %s for %s", response.status_code, url)
            return FetchResult(url, response.url, response.status_code, None)

        html = response.text
        self._write_cache(url, html)
        return FetchResult(url, response.url, response.status_code, html)

    def fetch_xml(self, url: str) -> str | None:
        self._throttle()
        try:
            response = self.session.get(url, timeout=self.config.request_timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            logger.warning("Could not fetch sitemap %s: %s", url, exc)
            return None

    # -- discovery ---------------------------------------------------------

    def is_crawlable(self, url: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.netloc.lower() != self._host:
            return False
        if any(parsed.path.startswith(p) for p in self.config.excluded_prefixes):
            return False
        suffix = Path(parsed.path).suffix.lower()
        if suffix and suffix not in (".html", ".htm", ".php"):
            return False
        return True

    def discover_sitemap_urls(self) -> list[SeedUrl]:
        """Walk the sitemap index and return every URL it advertises."""
        index_xml = self.fetch_xml(self.config.sitemap_index)
        if not index_xml:
            logger.warning("Sitemap index unavailable; relying on link crawl only")
            return []

        seeds: list[SeedUrl] = []
        seen: set[str] = set()

        for child_url in self._parse_sitemap_index(index_xml):
            content_type = self._content_type_for(child_url)
            child_xml = self.fetch_xml(child_url)
            if not child_xml:
                continue
            entries = self._parse_url_set(child_xml)
            logger.info("Sitemap %s -> %d URLs", child_url, len(entries))
            for loc, lastmod in entries:
                normalized = normalize_url(loc)
                if normalized and normalized not in seen and self.is_crawlable(normalized):
                    seen.add(normalized)
                    seeds.append(SeedUrl(normalized, content_type, lastmod))

        return seeds

    def _content_type_for(self, sitemap_url: str) -> str:
        name = Path(urlparse(sitemap_url).path).name
        key = name.replace("-sitemap.xml", "")
        return SITEMAP_CONTENT_TYPES.get(key, "page")

    @staticmethod
    def _parse_sitemap_index(xml_text: str) -> list[str]:
        try:
            root = ElementTree.fromstring(xml_text.encode("utf-8"))
        except ElementTree.ParseError as exc:
            logger.warning("Malformed sitemap index: %s", exc)
            return []
        return [
            loc.text.strip()
            for loc in root.findall("sm:sitemap/sm:loc", SITEMAP_NS)
            if loc.text
        ]

    @staticmethod
    def _parse_url_set(xml_text: str) -> list[tuple[str, str | None]]:
        try:
            root = ElementTree.fromstring(xml_text.encode("utf-8"))
        except ElementTree.ParseError as exc:
            logger.warning("Malformed sitemap: %s", exc)
            return []
        entries: list[tuple[str, str | None]] = []
        for url_el in root.findall("sm:url", SITEMAP_NS):
            loc = url_el.find("sm:loc", SITEMAP_NS)
            if loc is None or not loc.text:
                continue
            lastmod_el = url_el.find("sm:lastmod", SITEMAP_NS)
            lastmod = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else None
            entries.append((loc.text.strip(), lastmod))
        return entries
