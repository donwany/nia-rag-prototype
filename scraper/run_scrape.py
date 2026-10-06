"""Entry point: scrape nia.gov.gh into data/nia_website.md and friends.

    python -m scraper.run_scrape --verbose
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter, deque
from dataclasses import replace
from pathlib import Path

from .cleaner import clean_pages
from .config import CONFIG, ScraperConfig
from .crawler import Crawler, SeedUrl, normalize_url
from .exporters import write_assets, write_jsonl, write_markdown
from .office_locations import build_office_pages
from .parser import PageData, PageParser

logger = logging.getLogger("scraper")

# Order sections appear in the exported markdown.
TYPE_ORDER = {
    "page": 0,
    "service": 1,
    "news": 2,
    "category": 3,
    "discovered": 4,
    "office_location": 5,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape https://nia.gov.gh/")
    parser.add_argument("--limit", type=int, default=None, help="Max HTML pages to fetch")
    parser.add_argument("--delay", type=float, default=None, help="Seconds between requests")
    parser.add_argument("--no-cache", action="store_true", help="Ignore the on-disk cache")
    parser.add_argument("--skip-offices", action="store_true", help="Skip the store locator API")
    parser.add_argument("--no-crawl", action="store_true", help="Sitemap URLs only")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> ScraperConfig:
    config = CONFIG
    if args.delay is not None:
        config = replace(config, request_delay=args.delay)
    if args.output_dir is not None:
        out = args.output_dir.resolve()
        config = replace(
            config,
            data_dir=out,
            cache_dir=out / "cache",
            markdown_output=out / "nia_website.md",
            jsonl_output=out / "pages.jsonl",
            assets_output=out / "assets.json",
        )
    return config


def collect_pages(
    crawler: Crawler,
    parser: PageParser,
    seeds: list[SeedUrl],
    follow_links: bool,
    limit: int | None,
) -> list[PageData]:
    """Fetch seeds, then breadth-first follow internal links not already seen."""
    queue: deque[tuple[str, str, str | None, int]] = deque(
        (seed.url, seed.content_type, seed.lastmod, 0) for seed in seeds
    )
    seen: set[str] = {seed.url for seed in seeds}
    pages: list[PageData] = []
    failures = 0

    while queue:
        if limit is not None and len(pages) >= limit:
            logger.info("Reached page limit of %d", limit)
            break

        url, content_type, lastmod, depth = queue.popleft()
        result = crawler.fetch(url)
        if not result.ok:
            failures += 1
            continue

        page = parser.parse(url, result.html, content_type, lastmod)
        if page is None or page.word_count < 10:
            logger.debug("Skipping empty page %s", url)
            continue

        pages.append(page)
        if len(pages) % 25 == 0:
            logger.info("Parsed %d pages (queue: %d)", len(pages), len(queue))

        if not follow_links or depth >= crawler.config.max_crawl_depth:
            continue
        if len(seen) >= crawler.config.max_pages:
            continue

        for link in page.links:
            if not link.get("internal"):
                continue
            candidate = normalize_url(link["url"])
            if not candidate or candidate in seen:
                continue
            if not crawler.is_crawlable(candidate):
                continue
            # Office pages are JS-rendered; their data comes from the API.
            if "/office-locations/" in candidate:
                continue
            seen.add(candidate)
            queue.append((candidate, "discovered", None, depth + 1))

    if failures:
        logger.warning("%d URLs could not be fetched", failures)
    return pages


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    config = build_config(args)
    started = time.monotonic()

    crawler = Crawler(config=config, use_cache=not args.no_cache)
    parser = PageParser(config)

    logger.info("Discovering URLs from %s", config.sitemap_index)
    seeds = crawler.discover_sitemap_urls()
    # Office locations are handled through the store locator API instead.
    html_seeds = [s for s in seeds if s.content_type != "office_location"]
    logger.info(
        "Discovered %d URLs (%d HTML pages, %d office locations)",
        len(seeds),
        len(html_seeds),
        len(seeds) - len(html_seeds),
    )

    if not html_seeds:
        html_seeds = [SeedUrl(normalize_url(config.base_url), "page")]

    pages = collect_pages(
        crawler, parser, html_seeds, follow_links=not args.no_crawl, limit=args.limit
    )

    if not args.skip_offices:
        office_pages = build_office_pages(crawler.session, config)
        logger.info("Built %d office location records", len(office_pages))
        pages.extend(office_pages)

    if not pages:
        logger.error("No pages scraped; aborting")
        return 1

    stats = clean_pages(pages, config)
    logger.info(
        "Cleaned %d pages, removed %d boilerplate lines (%d distinct)",
        stats.pages_processed,
        stats.lines_removed,
        stats.boilerplate_lines,
    )

    pages.sort(key=lambda p: (TYPE_ORDER.get(p.content_type, 9), p.title.lower()))

    write_markdown(pages, config.markdown_output)
    write_jsonl(pages, config.jsonl_output)
    write_assets(pages, config.assets_output)

    by_type = Counter(p.content_type for p in pages)
    logger.info("Done in %.1fs", time.monotonic() - started)
    logger.info("Pages by type: %s", dict(by_type))
    logger.info("Total words: %d", sum(p.word_count for p in pages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
