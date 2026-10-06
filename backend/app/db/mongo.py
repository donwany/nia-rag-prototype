"""MongoDB connection lifecycle and index management."""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from ..config import Settings, settings as default_settings

logger = logging.getLogger(__name__)

USERS = "users"
CHATS = "chats"
MESSAGES = "messages"

_client: AsyncIOMotorClient | None = None


async def connect(config: Settings = default_settings) -> AsyncIOMotorDatabase:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(config.mongodb_uri, serverSelectionTimeoutMS=5000)
        logger.info("Connected to MongoDB database '%s'", config.mongodb_db)
    return _client[config.mongodb_db]


def get_database(config: Settings = default_settings) -> AsyncIOMotorDatabase:
    if _client is None:
        raise RuntimeError("MongoDB is not connected; call connect() on startup")
    return _client[config.mongodb_db]


async def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")


async def ensure_indexes(database: AsyncIOMotorDatabase) -> None:
    """Indexes backing login lookups and history queries."""
    await database[USERS].create_index([("email", ASCENDING)], unique=True)
    await database[CHATS].create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
    await database[MESSAGES].create_index([("chat_id", ASCENDING), ("created_at", ASCENDING)])
    await database[MESSAGES].create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    logger.info("MongoDB indexes ensured")


async def ping(config: Settings = default_settings) -> bool:
    try:
        database = get_database(config)
        await database.command("ping")
        return True
    except Exception as exc:
        logger.warning("MongoDB ping failed: %s", exc)
        return False
