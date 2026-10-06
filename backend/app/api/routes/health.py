"""Liveness and dependency checks."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from ...db import mongo
from ...db.vectorstore import count_documents
from ...models.schemas import HealthResponse, ServiceHealth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    mongo_ok = await mongo.ping()

    try:
        chunks = await asyncio.to_thread(count_documents)
        postgres_ok = True
    except Exception as exc:
        logger.warning("Postgres health check failed: %s", exc)
        chunks, postgres_ok = 0, False

    return HealthResponse(
        status="ok" if (mongo_ok and postgres_ok) else "degraded",
        services=ServiceHealth(
            postgres=postgres_ok, mongodb=mongo_ok, embedded_chunks=chunks
        ),
    )
