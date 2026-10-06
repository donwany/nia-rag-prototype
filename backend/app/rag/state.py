"""Shared state for the LangGraph RAG workflow."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage


class RAGState(TypedDict, total=False):
    # Input
    question: str
    chat_history: Annotated[list[BaseMessage], "Prior turns, oldest first"]

    # Working values
    search_query: str
    documents: list[Document]
    rewrite_count: int

    # Output
    generation: str
    sources: list[dict]
    grounded: bool
    # Set when retrieval could not run, as opposed to finding nothing.
    error: str | None
