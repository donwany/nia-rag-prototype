"""Cross-page boilerplate removal.

Selector-based stripping in :mod:`parser` removes the obvious chrome, but
Elementor leaves fragments of the mega-menu and footer embedded in ordinary
content containers. Those fragments are identifiable statistically: a line that
appears on most of the 450+ pages is navigation, not information.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

from .config import CONFIG, ScraperConfig
from .parser import PageData

logger = logging.getLogger(__name__)

# Minimum corpus size for frequency analysis to mean anything.
MIN_PAGES_FOR_ANALYSIS = 10

# Content types built from structured API data rather than scraped HTML. They
# contain no site chrome by construction, and their repetition is meaningful:
# every office genuinely shares the same opening hours, so frequency analysis
# would strip exactly the facts we want to keep.
SYNTHESIZED_CONTENT_TYPES = {"office_location"}

# Lines matching these are always dropped regardless of frequency. Blank lines
# are deliberately absent: they separate markdown blocks, and the header-aware
# splitter downstream depends on that structure.
ALWAYS_DROP = (
    re.compile(r"^(home|search|menu|close|toggle navigation|skip to content)$", re.I),
    re.compile(r"^©\s*\d{4}", re.I),
    re.compile(r"^(facebook|x\.com|twitter|instagram|youtube|linkedin)$", re.I),
    re.compile(r"^loading\.{0,3}$", re.I),
    re.compile(r"^(previous|next|read more|view all|learn more)$", re.I),
)


@dataclass
class CleanStats:
    pages_processed: int = 0
    boilerplate_lines: int = 0
    lines_removed: int = 0


class BoilerplateFilter:
    def __init__(self, config: ScraperConfig = CONFIG) -> None:
        self.config = config
        self._blocked: set[str] = set()
        self.stats = CleanStats()

    def fit(self, pages: list[PageData]) -> None:
        if len(pages) < MIN_PAGES_FOR_ANALYSIS:
            logger.info("Only %d pages; skipping frequency analysis", len(pages))
            return

        counter: Counter[str] = Counter()
        for page in pages:
            # Count each distinct line once per page.
            counter.update(set(self._candidate_lines(page.markdown)))

        cutoff = max(2, int(len(pages) * self.config.boilerplate_threshold))
        self._blocked = {line for line, count in counter.items() if count >= cutoff}
        self.stats.boilerplate_lines = len(self._blocked)
        logger.info(
            "Identified %d boilerplate lines (present on >= %d of %d pages)",
            len(self._blocked),
            cutoff,
            len(pages),
        )

    def _candidate_lines(self, markdown: str) -> list[str]:
        lines = []
        for raw in markdown.splitlines():
            line = raw.strip()
            if len(line) < self.config.boilerplate_min_length:
                continue
            # Never let table rows or images influence (or fall victim to) the
            # frequency filter; they carry page-specific data.
            if line.startswith("|") or line.startswith("!["):
                continue
            lines.append(line)
        return lines

    def transform(self, page: PageData) -> PageData:
        kept: list[str] = []
        removed = 0
        for raw in page.markdown.splitlines():
            line = raw.strip()
            if self._is_always_dropped(line):
                removed += 1
                continue
            if line in self._blocked and not line.startswith(("|", "![")):
                removed += 1
                continue
            kept.append(raw)

        cleaned = _collapse_blank_lines("\n".join(kept))

        # Safety net: if filtering gutted the page, keep the original text.
        if len(cleaned.split()) < 20 < len(page.markdown.split()):
            logger.debug("Boilerplate filter too aggressive on %s; keeping raw", page.url)
        else:
            page.markdown = cleaned
            page.word_count = len(cleaned.split())
            self.stats.lines_removed += removed

        self.stats.pages_processed += 1
        return page

    @staticmethod
    def _is_always_dropped(line: str) -> bool:
        return any(pattern.match(line) for pattern in ALWAYS_DROP)


def _collapse_blank_lines(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Drop duplicated consecutive lines, a common Elementor artefact where the
    # same widget is rendered for desktop and mobile breakpoints.
    out: list[str] = []
    for line in text.splitlines():
        if out and line.strip() and line.strip() == out[-1].strip():
            continue
        out.append(line)
    return "\n".join(out).strip()


def clean_pages(pages: list[PageData], config: ScraperConfig = CONFIG) -> CleanStats:
    """Fit the filter on the scraped HTML pages, then apply it in place."""
    scraped = [p for p in pages if p.content_type not in SYNTHESIZED_CONTENT_TYPES]
    filt = BoilerplateFilter(config)
    filt.fit(scraped)
    for page in scraped:
        filt.transform(page)
    return filt.stats
