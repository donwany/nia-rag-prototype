"""Persistence for conversations and their messages."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..db.mongo import CHATS, MESSAGES
from ..models.schemas import ChatDetail, ChatSummary, MessageOut, Source

logger = logging.getLogger(__name__)

# Turns of prior context handed to the model. Enough for follow-up questions
# without blowing up the prompt or the cost of every request.
HISTORY_TURNS = 6
TITLE_MAX_CHARS = 70


def _object_id(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def _title_from(question: str) -> str:
    title = " ".join(question.strip().split())
    if len(title) > TITLE_MAX_CHARS:
        title = title[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return title or "New conversation"


async def create_chat(
    database: AsyncIOMotorDatabase, user_id: str, first_question: str
) -> dict:
    now = datetime.now(timezone.utc)
    document = {
        "user_id": user_id,
        "title": _title_from(first_question),
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    result = await database[CHATS].insert_one(document)
    document["_id"] = result.inserted_id
    return document


async def get_chat(
    database: AsyncIOMotorDatabase, chat_id: str, user_id: str
) -> dict | None:
    object_id = _object_id(chat_id)
    if object_id is None:
        return None
    return await database[CHATS].find_one({"_id": object_id, "user_id": user_id})


async def resolve_chat(
    database: AsyncIOMotorDatabase, chat_id: str | None, user_id: str, question: str
) -> dict:
    """Return the requested conversation, creating one when absent.

    An unknown or foreign chat_id starts a new conversation rather than
    erroring, so a stale tab cannot wedge the client.
    """
    if chat_id:
        existing = await get_chat(database, chat_id, user_id)
        if existing is not None:
            return existing
        logger.info("Chat %s not found for user %s; starting a new one", chat_id, user_id)
    return await create_chat(database, user_id, question)


async def add_message(
    database: AsyncIOMotorDatabase,
    chat_id: ObjectId,
    user_id: str,
    role: str,
    content: str,
    sources: list[dict] | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    document = {
        "chat_id": chat_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "sources": sources or [],
        "created_at": now,
    }
    result = await database[MESSAGES].insert_one(document)
    document["_id"] = result.inserted_id

    await database[CHATS].update_one(
        {"_id": chat_id},
        {"$inc": {"message_count": 1}, "$set": {"updated_at": now}},
    )
    return document


async def get_history(
    database: AsyncIOMotorDatabase, chat_id: ObjectId, limit: int = HISTORY_TURNS
) -> list[dict]:
    """Most recent turns, oldest first, as ``{role, content}`` dicts."""
    cursor = (
        database[MESSAGES]
        .find({"chat_id": chat_id}, {"role": 1, "content": 1})
        .sort("created_at", -1)
        .limit(limit)
    )
    documents = await cursor.to_list(length=limit)
    documents.reverse()
    return [{"role": d["role"], "content": d["content"]} for d in documents]


async def list_chats(
    database: AsyncIOMotorDatabase, user_id: str, limit: int = 50
) -> list[ChatSummary]:
    cursor = (
        database[CHATS].find({"user_id": user_id}).sort("updated_at", -1).limit(limit)
    )
    documents = await cursor.to_list(length=limit)
    return [
        ChatSummary(
            id=str(d["_id"]),
            title=d.get("title", "Conversation"),
            message_count=d.get("message_count", 0),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )
        for d in documents
    ]


async def get_chat_detail(
    database: AsyncIOMotorDatabase, chat_id: str, user_id: str
) -> ChatDetail | None:
    chat = await get_chat(database, chat_id, user_id)
    if chat is None:
        return None

    cursor = database[MESSAGES].find({"chat_id": chat["_id"]}).sort("created_at", 1)
    documents = await cursor.to_list(length=500)

    return ChatDetail(
        id=str(chat["_id"]),
        title=chat.get("title", "Conversation"),
        message_count=chat.get("message_count", 0),
        created_at=chat["created_at"],
        updated_at=chat["updated_at"],
        messages=[
            MessageOut(
                id=str(d["_id"]),
                role=d["role"],
                content=d["content"],
                sources=[Source(**s) for s in d.get("sources", [])],
                created_at=d["created_at"],
            )
            for d in documents
        ],
    )


async def delete_chat(
    database: AsyncIOMotorDatabase, chat_id: str, user_id: str
) -> bool:
    chat = await get_chat(database, chat_id, user_id)
    if chat is None:
        return False
    await database[MESSAGES].delete_many({"chat_id": chat["_id"]})
    await database[CHATS].delete_one({"_id": chat["_id"]})
    logger.info("Deleted chat %s for user %s", chat_id, user_id)
    return True
