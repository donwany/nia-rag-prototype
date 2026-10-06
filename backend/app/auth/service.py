"""User persistence and authentication logic."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from ..db.mongo import USERS
from ..models.schemas import UserCreate, UserPublic
from .security import hash_password, verify_password

logger = logging.getLogger(__name__)


class EmailAlreadyRegistered(Exception):
    """Raised when registration targets an address that already exists."""


def to_public(document: dict) -> UserPublic:
    return UserPublic(
        id=str(document["_id"]),
        email=document["email"],
        full_name=document.get("full_name"),
        created_at=document["created_at"],
    )


def _normalise_email(email: str) -> str:
    return email.strip().lower()


async def create_user(database: AsyncIOMotorDatabase, payload: UserCreate) -> dict:
    now = datetime.now(timezone.utc)
    document = {
        "email": _normalise_email(payload.email),
        "password_hash": hash_password(payload.password),
        "full_name": (payload.full_name or "").strip() or None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await database[USERS].insert_one(document)
    except DuplicateKeyError as exc:
        raise EmailAlreadyRegistered(payload.email) from exc

    document["_id"] = result.inserted_id
    logger.info("Registered user %s", document["email"])
    return document


async def get_user_by_email(
    database: AsyncIOMotorDatabase, email: str
) -> dict | None:
    return await database[USERS].find_one({"email": _normalise_email(email)})


async def get_user_by_id(database: AsyncIOMotorDatabase, user_id: str) -> dict | None:
    try:
        object_id = ObjectId(user_id)
    except (InvalidId, TypeError):
        return None
    return await database[USERS].find_one({"_id": object_id})


async def authenticate(
    database: AsyncIOMotorDatabase, email: str, password: str
) -> dict | None:
    user = await get_user_by_email(database, email)
    if user is None:
        # Hash anyway so a missing account and a wrong password take a similar
        # amount of time, which avoids leaking which addresses are registered.
        verify_password(password, "$2b$12$" + "." * 53)
        return None
    if not verify_password(password, user.get("password_hash", "")):
        return None
    return user
