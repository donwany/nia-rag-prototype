"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from .auth.security import decode_access_token
from .auth.service import get_user_by_id
from .db.mongo import get_database

bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_db() -> AsyncIOMotorDatabase:
    return get_database()


DatabaseDep = Annotated[AsyncIOMotorDatabase, Depends(get_db)]


async def get_current_user(
    database: DatabaseDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> dict:
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_ERROR

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise CREDENTIALS_ERROR

    user_id = payload.get("sub")
    if not user_id:
        raise CREDENTIALS_ERROR

    user = await get_user_by_id(database, user_id)
    if user is None:
        raise CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]
