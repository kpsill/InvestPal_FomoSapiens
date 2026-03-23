from enum import Enum
import http
from datetime import datetime

from fastapi import (
    APIRouter, 
    Depends, 
    HTTPException,
    Query,
)
from pydantic import BaseModel

from services.session import (
    SessionService, 
)
from errors.session import SessionAlreadyExistsError
from errors.user_context import  UserContextNotFoundError
from dependencies import get_session_service


router = APIRouter()


class CreateSessionRequest(BaseModel):
    """
    Request model for creating a new session.
    
    Attributes:
        user_id (str): The ID of the user.
        session_id (str | None): The ID of the session. If not provided, a new ID will be generated.
    """
    user_id: str
    session_id: str | None = None


class RoleSchema(str, Enum):
    USER = "user"
    AGENT = "agent"


class MessageSchema(BaseModel):
    role: RoleSchema
    content: str
    created_at: str | None


class SessionSchema(BaseModel):
    session_id: str
    user_id: str
    messages: list[MessageSchema]


class SessionSummarySchema(BaseModel):
    session_id: str
    title: str
    created_at: datetime
    is_empty: bool


@router.get("/sessions", response_model=list[SessionSummarySchema])
async def list_user_sessions(
    user_id: str = Query(...),
    session_service: SessionService = Depends(get_session_service)
):
    """List all sessions for a given user. DB query is strictly filtered by user_id."""
    summaries = await session_service.list_sessions(user_id)
    return [
        SessionSummarySchema(
            session_id=s.session_id,
            title=s.title,
            created_at=s.created_at,
            is_empty=s.is_empty,
        )
        for s in summaries
    ]


@router.post("/session", response_model=SessionSchema, status_code=http.HTTPStatus.CREATED)
async def create_session(request: CreateSessionRequest, session_service: SessionService = Depends(get_session_service)):
    try:
        session = await session_service.create_session(request.user_id, request.session_id)
    except SessionAlreadyExistsError as e:
        raise HTTPException(status_code=http.HTTPStatus.CONFLICT, detail=str(e))
    except UserContextNotFoundError as e:
        raise HTTPException(status_code=http.HTTPStatus.BAD_REQUEST, detail=str(e))
    
    return SessionSchema(
        session_id=session.session_id,
        user_id=session.user_id,
        messages=[],
    )


@router.get("/session/{session_id}", response_model=SessionSchema)
async def get_session(session_id: str, session_service: SessionService = Depends(get_session_service)):
    session = await session_service.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=http.HTTPStatus.NOT_FOUND, detail="Session not found")
    
    # Convert Message objects to MessageSchema objects
    messages = [
        MessageSchema(
            role=RoleSchema(message.role),
            content=message.content,
            created_at=message.created_at,
        )
        for message in session.messages
    ]

    return SessionSchema(
        session_id=session.session_id,
        user_id=session.user_id,
        messages=messages,
    )


class RenameTitleRequest(BaseModel):
    title: str


@router.delete("/session/{session_id}", status_code=http.HTTPStatus.NO_CONTENT)
async def delete_session(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
):
    deleted = await session_service.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=http.HTTPStatus.NOT_FOUND, detail="Session not found")


@router.patch("/session/{session_id}/title", status_code=http.HTTPStatus.NO_CONTENT)
async def rename_session(
    session_id: str,
    body: RenameTitleRequest,
    session_service: SessionService = Depends(get_session_service),
):
    if not body.title.strip():
        raise HTTPException(status_code=http.HTTPStatus.BAD_REQUEST, detail="Title cannot be empty")
    updated = await session_service.rename_session(session_id, body.title)
    if not updated:
        raise HTTPException(status_code=http.HTTPStatus.NOT_FOUND, detail="Session not found")
