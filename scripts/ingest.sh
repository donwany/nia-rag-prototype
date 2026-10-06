#!/usr/bin/env bash
# Scrape nia.gov.gh (unless a corpus is already present) and embed it into
# PGVector. Run via: docker compose --profile ingest run --rm ingest [--reset]
set -euo pipefail

DATA_DIR="${DATA_DIR:-/data}"
PAGES="${DATA_DIR}/pages.jsonl"

cd /srv

if [[ "${1:-}" == "--rescrape" || ! -f "${PAGES}" ]]; then
  echo "==> Scraping https://nia.gov.gh/ into ${DATA_DIR}"
  python -m scraper.run_scrape --output-dir "${DATA_DIR}"
  shift || true
else
  echo "==> Reusing existing corpus at ${PAGES}"
  echo "    (pass --rescrape to refresh it from the live site)"
fi

echo "==> Embedding into PGVector"
python -m app.ingest.ingest --source "${PAGES}" "$@"

echo "==> Ingestion complete"
