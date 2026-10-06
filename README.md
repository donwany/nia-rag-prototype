# NIA RAG System

A Retrieval-Augmented Generation system built over the public website of Ghana's
**National Identification Authority** (<https://nia.gov.gh/>). It scrapes the site into a
markdown corpus, embeds it into PGVector, and serves grounded, cited answers through a
LangGraph workflow behind a FastAPI backend and a React chat interface.

Ask it things like *"How much does it cost to replace a Ghana Card?"* or *"Where is the NIA
office in Ablekuma Central?"* and it answers from the scraped content, with links back to the
source pages.

---

## Table of contents

- [NIA RAG System](#nia-rag-system)
  - [Table of contents](#table-of-contents)
  - [Architecture](#architecture)
  - [Prerequisites](#prerequisites)
  - [Quick start (Docker)](#quick-start-docker)
  - [Environment variables](#environment-variables)
  - [Running the scraper](#running-the-scraper)
  - [Running the ingestion job](#running-the-ingestion-job)
  - [Local development (without Docker)](#local-development-without-docker)
  - [API reference](#api-reference)
  - [Project layout](#project-layout)
  - [Troubleshooting](#troubleshooting)
  - [Notes and limitations](#notes-and-limitations)

---

## Architecture

```
          OFFLINE                                   RUNTIME
  ┌──────────────────────┐              ┌──────────────────────────────┐
  │ sitemap_index.xml    │              │  React + Vite  (port 5173)   │
  │        ↓             │              │        ↓  REST + SSE         │
  │ requests + BeautifulSoup            │  FastAPI       (port 8000)   │
  │        ↓             │              │     ↓            ↓           │
  │ data/nia_website.md  │              │  LangGraph    MongoDB        │
  │        ↓             │              │     ↓       (users, chats)   │
  │ chunk + embed        │─────────────▶│  PGVector  ←  retrieval      │
  │ (text-embedding-3-small)            │     ↓                        │
  └──────────────────────┘              │  gpt-4o-mini → cited answer  │
                                        └──────────────────────────────┘
```

Full design rationale, data models and the LangGraph state machine live in
[DESIGN.md](DESIGN.md).

**Stack:** Python, BeautifulSoup, Requests, LangChain, LangGraph, PGVector, FastAPI,
MongoDB, React, Docker.

---

## Prerequisites

| Requirement | Version | Notes |
| --- | --- | --- |
| Docker + Docker Compose | 24+ | The only hard requirement for the quick start |
| OpenAI API key | - | Used for both embeddings and chat completion |
| Python | 3.11+ | Only for running the scraper outside Docker |
| Node.js | 20+ | Only for frontend development outside Docker |

Ingesting the full corpus costs roughly **$0.01** in embedding calls, and each chat turn
costs a fraction of a cent on `gpt-4o-mini`.

---

## Quick start (Docker)

```bash
cd lesson21

# 1. Configure
cp .env.example .env
#    Edit .env and set OPENAI_API_KEY, then generate a signing secret:
#    JWT_SECRET=$(openssl rand -hex 32)

# 2. Start Postgres, MongoDB, the API and the web UI
docker compose up -d --build

# 3. Scrape the site and load the vector store (one-shot job, ~10 minutes)
docker compose --profile ingest run --rm ingest
```

Then open <http://localhost:5173>, register an account, and start asking questions.

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:5173> |
| API docs (Swagger) | <http://localhost:8000/docs> |
| Health check | <http://localhost:8000/api/health> |

Check everything came up cleanly:

```bash
docker compose ps
docker compose logs -f backend
```

Shut down, keeping data:

```bash
docker compose down
```

Shut down and wipe the databases:

```bash
docker compose down -v
```

---

## Environment variables

Copy `.env.example` to `.env`. The variables that matter most:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | - | **Required.** Embeddings and chat completion |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | Generation model |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model (1536 dimensions) |
| `JWT_SECRET` | - | **Required.** Token signing key; use `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Session lifetime |
| `POSTGRES_*` | see file | PGVector connection |
| `MONGODB_URI` | `mongodb://nia:...@mongo:27017` | User and chat history storage |
| `PGVECTOR_COLLECTION` | `nia_documents` | Vector collection name |
| `RETRIEVER_K` | `6` | Chunks retrieved per question |
| `MAX_QUERY_REWRITES` | `1` | Retry budget when retrieval returns nothing relevant |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated allowed origins |

> Never commit `.env`. It is already listed in `.gitignore`.

---

## Running the scraper

The scraper is standalone and needs no API key or database — useful for inspecting the
corpus before spending anything on embeddings.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scraper/requirements.txt

python -m scraper.run_scrape --verbose
```

It writes three files into `data/`:

| File | Contents |
| --- | --- |
| `nia_website.md` | The human-readable corpus: one section per page, with metadata and source URL |
| `pages.jsonl` | One JSON record per page, consumed by the ingestion job |
| `assets.json` | Every image, PDF, media file and outbound link found, with the pages citing them |

Useful flags:

```bash
python -m scraper.run_scrape --limit 20      # stop after 20 pages (quick test)
python -m scraper.run_scrape --no-cache      # bypass the on-disk HTML cache
python -m scraper.run_scrape --no-crawl      # sitemap URLs only, no link following
python -m scraper.run_scrape --skip-offices  # skip the office-location dataset
python -m scraper.run_scrape --delay 2.0     # be slower/politer between requests
```

**How discovery works.** URLs come from the site's Rank Math sitemap index
(`sitemap_index.xml`), covering pages, services, news posts and category archives. A
breadth-first link crawl then picks up anything the sitemap missed. `robots.txt` is honoured
and requests are throttled to roughly one per second. Fetched HTML is cached under
`data/cache/`, so re-runs are fast and cost the site nothing.

**Office locations are a special case.** The 307 `/office-locations/<slug>/` pages render
their addresses client-side via the Agile Store Locator plugin, so their HTML contains only a
title. The plugin reads from `/wp-admin/admin-ajax.php` — a path `robots.txt` explicitly
allows — which returns the full structured record for every office: region, Ghana Post GPS
digital address, phone, coordinates and opening hours. The scraper uses that endpoint rather
than fetching 307 empty pages.

---

## Running the ingestion job

Ingestion chunks the corpus, embeds it, and writes to PGVector. Under Docker:

```bash
docker compose --profile ingest run --rm ingest
```

To re-embed from scratch after changing the chunking strategy:

```bash
docker compose --profile ingest run --rm ingest --reset
```

Outside Docker, with Postgres reachable:

```bash
pip install -r backend/requirements.txt
python -m app.ingest.ingest --source ../data/pages.jsonl
```

Chunking notes: text is split on markdown headers first, then into ~1000-character chunks
with 150 characters of overlap. Each office location stays a single chunk so that
location questions retrieve one clean, complete record instead of fragments spread across
307 near-identical pages. Casing and punctuation are preserved deliberately — lowercasing
and stripping punctuation degrade transformer embeddings.

---

## Local development (without Docker)

Run only the databases in containers, and the application on the host:

```bash
docker compose up -d postgres mongo

docker exec -it nia-mongo mongosh \
  -u nia \
  -p nia_password \
  --authenticationDatabase admin

docker exec -it nia-postgres \
  psql -U nia -d nia_rag
```

**Backend:**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export $(grep -v '^#' ../.env | xargs)
export POSTGRES_HOST=localhost
export MONGODB_URI=mongodb://nia:nia_password@localhost:27017

uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173, proxies /api to localhost:8000
```

---

## API reference

All endpoints are prefixed with `/api`. Everything except `/health`, `/auth/register` and
`/auth/login` requires an `Authorization: Bearer <token>` header.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness plus Postgres and MongoDB connectivity |
| `POST` | `/auth/register` | Create an account; returns an access token |
| `POST` | `/auth/login` | Exchange credentials for an access token |
| `GET` | `/auth/me` | Current user profile |
| `POST` | `/chat` | Ask a question; returns the answer with sources |
| `POST` | `/chat/stream` | Same, streamed token-by-token over SSE |
| `GET` | `/chats` | List the current user's conversations |
| `GET` | `/chats/{chat_id}` | Full message history for one conversation |
| `DELETE` | `/chats/{chat_id}` | Delete a conversation |

Example:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"secret123","full_name":"Ada"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"How much does it cost to replace a Ghana Card?"}' | python3 -m json.tool
```

Interactive docs are at <http://localhost:8000/docs>.

---

## Project layout

```
lesson21/
├── scraper/                  # requests + BeautifulSoup site scraper
│   ├── config.py             # URLs, politeness settings, selectors
│   ├── crawler.py            # sitemap discovery, retries, caching, robots.txt
│   ├── parser.py             # HTML → markdown rendering, asset extraction
│   ├── cleaner.py            # cross-page boilerplate removal
│   ├── office_locations.py   # store-locator API extraction
│   ├── exporters.py          # markdown / JSONL / asset manifest writers
│   └── run_scrape.py         # CLI entry point
├── data/                     # scraper output (nia_website.md is the deliverable)
├── backend/
│   └── app/
│       ├── api/routes/       # auth, chat, history, health
│       ├── auth/             # JWT, password hashing, current-user dependency
│       ├── db/               # Mongo and PGVector clients
│       ├── ingest/           # chunking and embedding pipeline
│       └── rag/              # LangGraph workflow, retriever, prompts
├── frontend/                 # React + Vite + TypeScript chat UI
├── docker-compose.yml
├── DESIGN.md                 # architecture and design rationale
└── README.md
```

---

## Troubleshooting

**`OPENAI_API_KEY` errors on startup.** The backend reads `.env` from the project root. Confirm
the file exists and the key is set: `docker compose config | grep OPENAI`.

**Chat returns 503 "cannot reach its knowledge base".** Either the ingest job has not run or
`OPENAI_API_KEY` is invalid. Check the embedded chunk count, which `/api/health` also reports:

```bash
curl -s http://localhost:8000/api/health
docker compose exec postgres psql -U nia -d nia_rag \
  -c 'SELECT count(*) FROM langchain_pg_embedding;'
```

A count of zero means you still need `docker compose --profile ingest run --rm ingest`.

**Chat answers "I could not find anything on the NIA website" for a question you expect it to
know.** This one is genuine: retrieval ran but nothing cleared the relevance bar. Try phrasing
the question with official terminology ("Ghana Card" rather than "ID card"), or widen
retrieval with `RETRIEVER_K=10`.

**Scraper is slow.** That is intentional: requests are throttled to one per second to be a
good citizen, and nia.gov.gh itself responds slowly. The first full run takes around ten
minutes; subsequent runs hit the cache in `data/cache/` and finish in seconds.

**Port already in use.** Change the host-side port mappings in `docker-compose.yml`, for
example `"5433:5432"` for Postgres.

**Backend cannot reach the databases.** Inside Compose use the service names `postgres` and
`mongo`; from the host use `localhost`. Mixing the two is the usual cause.

---

## Notes and limitations

- Content is a snapshot. Re-run the scraper and ingest job to pick up site changes.
- Answers are grounded in the scraped corpus only; the system declines rather than guessing
  when retrieval comes up empty.
- This is an educational project and is not affiliated with or endorsed by the National
  Identification Authority. Always confirm official details at <https://nia.gov.gh/>.
