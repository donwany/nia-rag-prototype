"""Extraction of NIA office locations.

The 307 ``/office-locations/<slug>/`` pages render nothing useful server-side:
the addresses are injected at runtime by the Agile Store Locator plugin, so
scraping their HTML yields only the page title. The plugin sources its data
from ``/wp-admin/admin-ajax.php``, which ``robots.txt`` explicitly allows
(``Allow: /wp-admin/admin-ajax.php``), and that endpoint returns the complete,
structured record for every office: region, Ghana Post GPS address, phone,
coordinates and opening hours.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import requests

from .config import CONFIG, ScraperConfig
from .parser import PageData

logger = logging.getLogger(__name__)

AJAX_PATH = "/wp-admin/admin-ajax.php"
AJAX_PARAMS = {"action": "asl_load_stores", "load_all": "1", "layout": "1"}

DAY_LABELS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}


def _titlecase(value: str) -> str:
    """ALL-CAPS source data reads poorly and embeds slightly worse."""
    value = (value or "").strip()
    if not value:
        return ""
    if value.isupper():
        return " ".join(word.capitalize() for word in value.split())
    return value


def _format_hours(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    lines: list[str] = []
    for key, label in DAY_LABELS.items():
        value = data.get(key)
        if not value or value == "0":
            lines.append(f"{label}: Closed")
        elif isinstance(value, list):
            lines.append(f"{label}: {', '.join(str(v) for v in value)}")
        else:
            lines.append(f"{label}: {value}")
    return lines


def fetch_office_locations(
    session: requests.Session, config: ScraperConfig = CONFIG
) -> list[dict]:
    url = config.base_url.rstrip("/") + AJAX_PATH
    try:
        response = session.get(url, params=AJAX_PARAMS, timeout=config.request_timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Could not load office locations from %s: %s", url, exc)
        return []

    if not isinstance(payload, list):
        logger.warning("Unexpected office locator payload type: %s", type(payload))
        return []
    logger.info("Loaded %d office locations from the store locator API", len(payload))
    return payload


def office_to_page(record: dict, config: ScraperConfig = CONFIG) -> PageData | None:
    name = _titlecase(record.get("title", ""))
    if not name:
        return None

    slug = record.get("slug") or name.lower().replace(" ", "-")
    url = f"{config.base_url.rstrip('/')}/office-locations/{slug}/"
    region = _titlecase(record.get("state", "")) or "Unspecified region"
    digital_address = (record.get("digital_address") or "").strip()
    phone = (record.get("phone") or "").strip()
    street = (record.get("street") or "").strip()
    city = _titlecase(record.get("city", ""))
    lat, lng = (record.get("lat") or "").strip(), (record.get("lng") or "").strip()
    days = (record.get("days_str") or "").strip()
    website = (record.get("website") or "").strip()

    # A natural-language lead sentence materially improves embedding recall for
    # questions phrased as "where is the NIA office in X".
    lead = (
        f"The National Identification Authority (NIA) office for {name} "
        f"is located in the {region} of Ghana."
    )
    if digital_address:
        lead += f" Its Ghana Post GPS digital address is {digital_address}."
    if phone:
        lead += f" It can be reached on {phone}."

    details = [f"- Office: {name} NIA Office", f"- Region: {region}"]
    if city:
        details.append(f"- City/Town: {city}")
    if street:
        details.append(f"- Street address: {street}")
    if digital_address:
        details.append(f"- Ghana Post GPS digital address: {digital_address}")
    if phone:
        details.append(f"- Telephone: {phone}")
    if days:
        details.append(f"- Open on: {days}")
    if lat and lng:
        details.append(f"- Coordinates: {lat}, {lng}")
    if website:
        details.append(f"- Book an appointment: {website}")

    hours = _format_hours(record.get("open_hours", ""))
    sections = [lead, "", "\n".join(details)]
    if hours:
        sections += ["", "Opening hours:", "\n".join(f"- {h}" for h in hours)]

    markdown = "\n".join(sections).strip()

    return PageData(
        url=url,
        title=f"{name} NIA Office - {region}",
        content_type="office_location",
        description=lead,
        canonical=url,
        markdown=markdown,
        headings=[f"{name} NIA Office"],
        word_count=len(markdown.split()),
        scraped_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def build_office_pages(
    session: requests.Session, config: ScraperConfig = CONFIG
) -> list[PageData]:
    records = fetch_office_locations(session, config)
    pages = [page for page in (office_to_page(r, config) for r in records) if page]
    pages.sort(key=lambda p: p.title)
    return pages
