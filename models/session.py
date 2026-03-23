from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

class MessageRole(str, Enum):
    USER = "user"
    AGENT = "agent"


class Message(BaseModel):
    role: MessageRole
    content: str
    created_at: str | None = None


class Session(BaseModel):
    session_id: str
    user_id: str
    messages: list[Message]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    custom_title: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    title: str          # custom_title if set, else first user message, else "New Chat"
    created_at: datetime
    is_empty: bool = False  # True if no messages yet
