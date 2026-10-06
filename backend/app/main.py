"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import auth, chat, health, history
from .config import settings
from .db import mongo

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = await mongo.connect(settings)
    try:
        await mongo.ensure_indexes(database)
    except Exception as exc:
        # The API is still useful for health checks if Mongo is briefly down.
        logger.error("Could not prepare MongoDB indexes: %s", exc)

    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY is not set; chat endpoints will fail")

    logger.info("%s ready", settings.app_name)
    yield
    await mongo.close()


app = FastAPI(
    title=settings.app_name,
    description=(
        "Retrieval-Augmented Generation over the National Identification "
        "Authority of Ghana website (https://nia.gov.gh/)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Flatten Pydantic's error list into a single readable message."""
    messages = []
    for error in exc.errors():
        location = " -> ".join(str(part) for part in error["loc"] if part != "body")
        messages.append(f"{location}: {error['msg']}" if location else error["msg"])
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "; ".join(messages) or "Invalid request"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(history.router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }
