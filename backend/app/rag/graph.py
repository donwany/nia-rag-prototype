"""The LangGraph workflow that turns a question into a grounded answer.

    condense -> retrieve -> grade -+-> generate -> END
                   ^               |
                   |               +-> rewrite (budgeted) --+
                   +-------------------------------------- +
                                   |
                                   +-> fallback -> END

Grading sits between retrieval and generation so that a semantically close but
topically irrelevant chunk cannot pull the answer off course; when nothing
survives grading the question is rewritten once in official NIA vocabulary and
retried, and only then do we fall back to declining.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import AsyncIterator

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from ..config import Settings, settings as default_settings
from .prompts import (
    ANSWER_PROMPT,
    CONDENSE_PROMPT,
    GRADE_PROMPT,
    NO_CONTEXT_MESSAGE,
    REWRITE_PROMPT,
)
from .retriever import RetrievalError, format_context, format_sources, retrieve
from .state import RAGState

logger = logging.getLogger(__name__)

# Tag applied to the answering model so the SSE layer can isolate its tokens
# from the auxiliary LLM calls (condensing, grading, rewriting).
GENERATION_TAG = "final_answer"


class RelevanceGrades(BaseModel):
    """Which retrieved documents are worth passing to the generator."""

    relevant_indices: list[int] = Field(
        default_factory=list,
        description="1-based indices of the documents relevant to the question",
    )


@lru_cache
def get_llm(config: Settings = default_settings, streaming: bool = False) -> ChatOpenAI:
    if not config.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set; cannot create the chat model")
    return ChatOpenAI(
        model=config.openai_chat_model,
        api_key=config.openai_api_key,
        temperature=config.llm_temperature,
        streaming=streaming,
        timeout=60,
        max_retries=2,
    )


def to_messages(history: list[dict] | None) -> list[BaseMessage]:
    """Convert stored ``{role, content}`` turns into LangChain messages."""
    messages: list[BaseMessage] = []
    for turn in history or []:
        role = (turn.get("role") or "").lower()
        content = turn.get("content") or ""
        if not content:
            continue
        if role in ("user", "human"):
            messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            messages.append(AIMessage(content=content))
    return messages


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


async def condense_node(state: RAGState) -> RAGState:
    """Resolve pronouns and ellipsis against the conversation so retrieval works."""
    question = state["question"]
    history = state.get("chat_history") or []
    if not history:
        return {"search_query": question, "rewrite_count": 0}

    chain = CONDENSE_PROMPT | get_llm() | StrOutputParser()
    try:
        condensed = (await chain.ainvoke({"question": question, "chat_history": history})).strip()
    except Exception as exc:
        logger.warning("Condense step failed (%s); using the raw question", exc)
        condensed = question

    if condensed and condensed != question:
        logger.debug("Condensed %r -> %r", question, condensed)
    return {"search_query": condensed or question, "rewrite_count": 0}


async def retrieve_node(state: RAGState) -> RAGState:
    query = state.get("search_query") or state["question"]
    try:
        documents = await retrieve(query)
    except RetrievalError as exc:
        return {"documents": [], "error": str(exc)}
    logger.debug("Retrieved %d documents for %r", len(documents), query)
    return {"documents": documents, "error": None}


async def grade_node(state: RAGState) -> RAGState:
    documents = state.get("documents") or []
    if not documents:
        return {"documents": []}

    listing = "\n\n".join(
        f"[{i}] {d.metadata.get('title', '')}\n{d.page_content[:600]}"
        for i, d in enumerate(documents, start=1)
    )
    chain = GRADE_PROMPT | get_llm().with_structured_output(RelevanceGrades)

    try:
        grades: RelevanceGrades = await chain.ainvoke(
            {"question": state.get("search_query") or state["question"], "documents": listing}
        )
        keep = {i for i in grades.relevant_indices if 1 <= i <= len(documents)}
    except Exception as exc:
        # A grading failure should degrade to "trust retrieval", not to silence.
        logger.warning("Grading failed (%s); keeping all retrieved documents", exc)
        return {"documents": documents}

    filtered = [d for i, d in enumerate(documents, start=1) if i in keep]
    logger.debug("Grading kept %d/%d documents", len(filtered), len(documents))
    return {"documents": filtered}


async def rewrite_node(state: RAGState) -> RAGState:
    chain = REWRITE_PROMPT | get_llm() | StrOutputParser()
    original = state.get("search_query") or state["question"]
    try:
        rewritten = (await chain.ainvoke({"question": original})).strip()
    except Exception as exc:
        logger.warning("Rewrite failed (%s); reusing the original query", exc)
        rewritten = original
    logger.debug("Rewrote %r -> %r", original, rewritten)
    return {
        "search_query": rewritten or original,
        "rewrite_count": state.get("rewrite_count", 0) + 1,
    }


async def generate_node(state: RAGState) -> RAGState:
    documents: list[Document] = state.get("documents") or []
    chain = (
        ANSWER_PROMPT
        | get_llm(streaming=True).with_config(tags=[GENERATION_TAG])
        | StrOutputParser()
    )
    answer = await chain.ainvoke(
        {
            "context": format_context(documents),
            "question": state["question"],
            "chat_history": state.get("chat_history") or [],
        }
    )
    return {
        "generation": answer.strip(),
        "sources": format_sources(documents),
        "grounded": True,
    }


async def fallback_node(state: RAGState) -> RAGState:
    logger.info("No relevant context for %r", state.get("question"))
    return {"generation": NO_CONTEXT_MESSAGE, "sources": [], "grounded": False}


def decide_after_grading(state: RAGState) -> str:
    if state.get("documents"):
        return "generate"
    # Rewriting cannot help when retrieval itself is broken.
    if state.get("error"):
        return "fallback"
    if state.get("rewrite_count", 0) < default_settings.max_query_rewrites:
        return "rewrite"
    return "fallback"


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------


@lru_cache
def build_graph():
    builder = StateGraph(RAGState)
    builder.add_node("condense", condense_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("grade", grade_node)
    builder.add_node("rewrite", rewrite_node)
    builder.add_node("generate", generate_node)
    builder.add_node("fallback", fallback_node)

    builder.set_entry_point("condense")
    builder.add_edge("condense", "retrieve")
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges(
        "grade",
        decide_after_grading,
        {"generate": "generate", "rewrite": "rewrite", "fallback": "fallback"},
    )
    builder.add_edge("rewrite", "retrieve")
    builder.add_edge("generate", END)
    builder.add_edge("fallback", END)

    return builder.compile()


def _initial_state(question: str, history: list[dict] | None) -> RAGState:
    return {
        "question": question.strip(),
        "chat_history": to_messages(history),
        "rewrite_count": 0,
        "documents": [],
        "error": None,
    }


class PipelineError(RuntimeError):
    """The workflow could not run because a dependency is unavailable."""


async def answer_question(question: str, history: list[dict] | None = None) -> dict:
    """Run the workflow to completion and return the answer plus its sources."""
    result = await build_graph().ainvoke(_initial_state(question, history))
    if result.get("error"):
        raise PipelineError(result["error"])
    return {
        "answer": result.get("generation", NO_CONTEXT_MESSAGE),
        "sources": result.get("sources", []),
        "grounded": result.get("grounded", False),
    }


async def stream_answer(
    question: str, history: list[dict] | None = None
) -> AsyncIterator[dict]:
    """Yield progress events, answer tokens, and a final payload with sources.

    Event shapes:
        {"type": "status", "node": "retrieve"}
        {"type": "token",  "value": "Ghana"}
        {"type": "done",   "answer": ..., "sources": [...], "grounded": true}
    """
    graph = build_graph()
    final: dict = {}
    streamed_any = False

    async for event in graph.astream_events(
        _initial_state(question, history), version="v2"
    ):
        kind = event["event"]

        if kind == "on_chain_start" and event.get("name") in {
            "condense",
            "retrieve",
            "grade",
            "rewrite",
            "generate",
            "fallback",
        }:
            yield {"type": "status", "node": event["name"]}

        elif kind == "on_chat_model_stream" and GENERATION_TAG in (event.get("tags") or []):
            chunk = event["data"]["chunk"]
            text = getattr(chunk, "content", "") or ""
            if text:
                streamed_any = True
                yield {"type": "token", "value": text}

        elif kind == "on_chain_end" and event.get("name") == "LangGraph":
            final = event["data"].get("output") or {}

    if final.get("error"):
        logger.error("Retrieval unavailable: %s", final["error"])
        yield {
            "type": "error",
            "detail": (
                "The assistant cannot reach its knowledge base right now. "
                "Check that the vector store has been populated and that "
                "OPENAI_API_KEY is valid."
            ),
        }
        return

    answer = (final.get("generation") or "").strip() or NO_CONTEXT_MESSAGE
    # The fallback path never touches the streaming model, so emit its text
    # here to keep the client's rendering logic uniform.
    if not streamed_any:
        yield {"type": "token", "value": answer}

    yield {
        "type": "done",
        "answer": answer,
        "sources": final.get("sources", []),
        "grounded": final.get("grounded", False),
    }
