"""Conversation history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status

from ...deps import CurrentUser, DatabaseDep
from ...models.schemas import ChatDetail, ChatSummary
from ...services import chat_service

router = APIRouter(prefix="/chats", tags=["history"])


@router.get("", response_model=list[ChatSummary])
async def list_chats(
    database: DatabaseDep,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ChatSummary]:
    return await chat_service.list_chats(database, str(current_user["_id"]), limit)


@router.get("/{chat_id}", response_model=ChatDetail)
async def get_chat(
    chat_id: str, database: DatabaseDep, current_user: CurrentUser
) -> ChatDetail:
    detail = await chat_service.get_chat_detail(
        database, chat_id, str(current_user["_id"])
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return detail


@router.delete(
    "/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_chat(
    chat_id: str, database: DatabaseDep, current_user: CurrentUser
) -> Response:
    deleted = await chat_service.delete_chat(
        database, chat_id, str(current_user["_id"])
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
