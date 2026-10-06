"""Registration, login and profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ...auth.security import create_access_token
from ...auth.service import (
    EmailAlreadyRegistered,
    authenticate,
    create_user,
    to_public,
)
from ...deps import CurrentUser, DatabaseDep
from ...models.schemas import Token, UserCreate, UserLogin, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token(user: dict) -> Token:
    token, expires_in = create_access_token(str(user["_id"]))
    return Token(
        access_token=token,
        expires_in=expires_in,
        user=to_public(user),
    )


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, database: DatabaseDep) -> Token:
    try:
        user = await create_user(database, payload)
    except EmailAlreadyRegistered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )
    return _issue_token(user)


@router.post("/login", response_model=Token)
async def login(payload: UserLogin, database: DatabaseDep) -> Token:
    user = await authenticate(database, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_token(user)


@router.get("/me", response_model=UserPublic)
async def me(current_user: CurrentUser) -> UserPublic:
    return to_public(current_user)
