from abc import ABC, abstractmethod
from datetime import datetime, timezone
import uuid

from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient

from config import settings
from models.session import (
    Session,
    SessionSummary,
    Message,
)
from errors.user_context import UserContextNotFoundError
from errors.session import (
    SessionAlreadyExistsError,
    SessionNotFoundError,
)


class SessionService(ABC):
    @abstractmethod
    async def create_session(self, user_id: str, session_id: str | None = None) -> Session:
        pass

    @abstractmethod
    async def get_session(self, session_id: str) -> Session | None:
        pass

    @abstractmethod
    async def add_message(self, session_id: str, message: Message) -> Session | None:
        pass

    @abstractmethod
    async def list_sessions(self, user_id: str, limit: int = 30) -> list[SessionSummary]:
        pass

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        pass

    @abstractmethod
    async def rename_session(self, session_id: str, new_title: str) -> bool:
        pass


class MessageMongoDoc(Message):
    pass


class SessionMongoDoc(BaseModel):
    sessionID: str
    user_id: str
    messages: list[MessageMongoDoc]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    custom_title: str | None = None


class MongoDBSessionService(SessionService):
    def __init__(self, mongo_client: AsyncMongoClient):
        self.db = mongo_client[settings.MONGO_DB_NAME]

    async def create_session(self, user_id: str, session_id: str | None = None) -> Session:
        """
        Create a new session for the user.
        
        Args:
            user_id (str): The ID of the user.
            session_id (str | None): The ID of the session. If not provided, a new ID will be generated.
        
        Returns:
            Session: The created session.
        
        Raises:
            SessionAlreadyExistsError: If the session already exists.
        """
        session_collection = self.db[settings.SESSION_COLLECTION_NAME]
        user_context_collection = self.db[settings.USER_CONTEXT_COLLECTION_NAME]

        if session_id:
            # Check if session already exists for the given id
            session = await self.get_session(session_id)
            if session:
                raise SessionAlreadyExistsError(f"Session {session_id} already exists")
        else:
            session_id = str(uuid.uuid4())

        # Check if user_id is valid
        user_context = await user_context_collection.find_one({"user_id": user_id})
        if not user_context:
            raise UserContextNotFoundError(f"User context not found for user_id: {user_id}")

        session_doc = SessionMongoDoc(sessionID=session_id, user_id=user_id, messages=[])
        await session_collection.insert_one(session_doc.model_dump())

        return Session(
            session_id=session_doc.sessionID,
            user_id=session_doc.user_id,
            messages=[],
            created_at=session_doc.created_at,
        )
    
    async def get_session(self, session_id: str) -> Session | None:
        session_collection = self.db[settings.SESSION_COLLECTION_NAME]
        doc = await session_collection.find_one({"sessionID": session_id})
        if not doc:
            return None

        mongo_doc = SessionMongoDoc.model_validate(doc)

        return Session(
            session_id=mongo_doc.sessionID,
            user_id=mongo_doc.user_id,
            messages=[
                Message(
                    role=msg.role,
                    content=msg.content,
                    created_at=msg.created_at,
                )
                for msg in mongo_doc.messages
            ],
            created_at=mongo_doc.created_at,
        )

    async def add_message(self, session_id: str, message: Message) -> Session | None:
        session_collection = self.db[settings.SESSION_COLLECTION_NAME]

        session = await self.get_session(session_id)
        if not session:
            raise SessionNotFoundError("Session not found")

        # Map Message to MessageMongoDoc
        message_doc = MessageMongoDoc(
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )

        await session_collection.update_one(
            {"sessionID": session_id},
            {"$push": {"messages": message_doc.model_dump()}}
        )

        session.messages.append(message)

        return session

    async def list_sessions(self, user_id: str, limit: int = 30) -> list[SessionSummary]:
        session_collection = self.db[settings.SESSION_COLLECTION_NAME]
        cursor = session_collection.find(
            {"user_id": user_id},  # SECURITY: strictly filtered by user_id
            {"sessionID": 1, "messages": {"$slice": 1}, "created_at": 1, "custom_title": 1}
        ).sort("created_at", -1).limit(limit)

        summaries = []
        async for doc in cursor:
            messages = doc.get("messages", [])
            is_empty = len(messages) == 0
            # Use custom title first, then first user message, then "New Chat"
            if doc.get("custom_title"):
                title = doc["custom_title"]
            else:
                title = "New Chat"
                for msg in messages:
                    if msg.get("role") == "user" and msg.get("content"):
                        title = msg["content"][:60]
                        if len(msg["content"]) > 60:
                            title += "..."
                        break
            created_at = doc.get("created_at", datetime.now(timezone.utc))
            summaries.append(SessionSummary(
                session_id=doc["sessionID"],
                title=title,
                created_at=created_at,
                is_empty=is_empty,
            ))
        return summaries

    async def delete_session(self, session_id: str) -> bool:
        session_collection = self.db[settings.SESSION_COLLECTION_NAME]
        result = await session_collection.delete_one({"sessionID": session_id})
        return result.deleted_count > 0

    async def rename_session(self, session_id: str, new_title: str) -> bool:
        session_collection = self.db[settings.SESSION_COLLECTION_NAME]
        result = await session_collection.update_one(
            {"sessionID": session_id},
            {"$set": {"custom_title": new_title.strip()}}
        )
        return result.modified_count > 0