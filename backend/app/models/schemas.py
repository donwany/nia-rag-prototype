"""Pydantic request and response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# bcrypt silently truncates beyond 72 bytes, so reject longer passwords rather
# than letting two different passwords authenticate the same account.
MAX_PASSWORD_BYTES = 72


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)

    @field_validator("password")
    @classmethod
    def _bcrypt_safe(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError("Password must be at most 72 bytes when UTF-8 encoded")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str | None = None
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class Source(BaseModel):
    index: int
    title: str
    url: str
    section: str = ""
    content_type: str = ""
    score: float = 0.0
    snippet: str = ""


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    chat_id: str | None = None

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question must not be empty")
        return cleaned


class ChatResponse(BaseModel):
    chat_id: str
    question: str
    answer: str
    sources: list[Source] = Field(default_factory=list)
    grounded: bool = False
    created_at: datetime


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    sources: list[Source] = Field(default_factory=list)
    created_at: datetime


class ChatSummary(BaseModel):
    id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatDetail(ChatSummary):
    messages: list[MessageOut] = Field(default_factory=list)


class ServiceHealth(BaseModel):
    postgres: bool
    mongodb: bool
    embedded_chunks: int = 0


class HealthResponse(BaseModel):
    status: str
    services: ServiceHealth


class ErrorResponse(BaseModel):
    detail: str
