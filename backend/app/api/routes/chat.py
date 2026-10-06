"""Question answering endpoints, buffered and streamed."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from ...deps import CurrentUser, DatabaseDep
from ...models.schemas import ChatRequest, ChatResponse, Source
from ...rag.graph import PipelineError, answer_question, stream_answer
from ...services import chat_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Stops nginx from buffering the stream and defeating the point of SSE.
    "X-Accel-Buffering": "no",
}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest, database: DatabaseDep, current_user: CurrentUser
) -> ChatResponse:
    user_id = str(current_user["_id"])
    chat_doc = await chat_service.resolve_chat(
        database, payload.chat_id, user_id, payload.question
    )
    history = await chat_service.get_history(database, chat_doc["_id"])
    await chat_service.add_message(
        database, chat_doc["_id"], user_id, "user", payload.question
    )

    try:
        result = await answer_question(payload.question, history)
    except PipelineError as exc:
        logger.error("Knowledge base unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The assistant cannot reach its knowledge base. Check that the "
                "ingest job has run and that OPENAI_API_KEY is valid."
            ),
        )
    except Exception as exc:
        logger.exception("RAG pipeline failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant is temporarily unavailable. Please try again.",
        )

    message = await chat_service.add_message(
        database,
        chat_doc["_id"],
        user_id,
        "assistant",
        result["answer"],
        result["sources"],
    )

    return ChatResponse(
        chat_id=str(chat_doc["_id"]),
        question=payload.question,
        answer=result["answer"],
        sources=[Source(**s) for s in result["sources"]],
        grounded=result["grounded"],
        created_at=message["created_at"],
    )


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest, database: DatabaseDep, current_user: CurrentUser
) -> StreamingResponse:
    user_id = str(current_user["_id"])
    chat_doc = await chat_service.resolve_chat(
        database, payload.chat_id, user_id, payload.question
    )
    history = await chat_service.get_history(database, chat_doc["_id"])
    await chat_service.add_message(
        database, chat_doc["_id"], user_id, "user", payload.question
    )

    async def event_stream() -> AsyncIterator[str]:
        chat_id = str(chat_doc["_id"])
        yield _sse({"type": "start", "chat_id": chat_id})

        answer = ""
        sources: list[dict] = []
        grounded = False
        try:
            async for event in stream_answer(payload.question, history):
                if event["type"] == "done":
                    answer = event["answer"]
                    sources = event["sources"]
                    grounded = event["grounded"]
                    yield _sse(
                        {
                            "type": "done",
                            "chat_id": chat_id,
                            "answer": answer,
                            "sources": sources,
                            "grounded": grounded,
                        }
                    )
                else:
                    yield _sse(event)
        except Exception as exc:
            logger.exception("Streaming failed: %s", exc)
            yield _sse(
                {
                    "type": "error",
                    "detail": "The assistant is temporarily unavailable.",
                }
            )
            return

        # Persist only once the stream completed, so an aborted request does
        # not leave a truncated answer in the user's history.
        if answer:
            await chat_service.add_message(
                database, chat_doc["_id"], user_id, "assistant", answer, sources
            )

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )
