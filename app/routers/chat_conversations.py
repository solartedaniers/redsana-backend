import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.groq_client import GroqClient, GroqClientError, get_groq_client
from app.core.security import get_current_claims
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.chat_conversation_sqlalchemy_repository import SqlAlchemyChatConversationRepository
from app.repositories.chat_message_sqlalchemy_repository import SqlAlchemyChatMessageRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.schemas.chat_conversation import (
    ChatConversationRead,
    ChatConversationRename,
    ChatMessageRead,
    ChatSendMessageRequest,
    ChatSendMessageResponse,
)
from app.services.chat_conversation_service import ChatConversationNotFoundError, ChatConversationService
from app.services.security_chat_context_service import SecurityChatContextBuilder
from app.services.security_chat_service import SecurityChatService

router = APIRouter(prefix="/api/conversations", tags=["chat-conversations"])


def _to_conversation_read(conversation: ChatConversation) -> ChatConversationRead:
    return ChatConversationRead(id=str(conversation.id), title=conversation.title, updated_at=conversation.updated_at)


def _to_message_read(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(
        id=str(message.id), role=message.role, content=message.content, created_at=message.created_at
    )


def _owner_id(claims: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(claims["sub"])


def _get_service(db: Session = Depends(get_db)) -> ChatConversationService:
    return ChatConversationService(
        conversation_repository=SqlAlchemyChatConversationRepository(db),
        message_repository=SqlAlchemyChatMessageRepository(db),
    )


@router.get("", response_model=list[ChatConversationRead])
def list_conversations(
    claims: dict[str, Any] = Depends(get_current_claims),
    service: ChatConversationService = Depends(_get_service),
) -> list[ChatConversationRead]:
    conversations = service.list_conversations(_owner_id(claims))
    return [_to_conversation_read(conversation) for conversation in conversations]


@router.post("", response_model=ChatConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(
    claims: dict[str, Any] = Depends(get_current_claims),
    service: ChatConversationService = Depends(_get_service),
) -> ChatConversationRead:
    conversation = service.create_conversation(_owner_id(claims))
    return _to_conversation_read(conversation)


@router.patch("/{conversation_id}", response_model=ChatConversationRead)
def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ChatConversationRename,
    claims: dict[str, Any] = Depends(get_current_claims),
    service: ChatConversationService = Depends(_get_service),
) -> ChatConversationRead:
    try:
        conversation = service.rename_conversation(conversation_id, _owner_id(claims), payload.title)
    except ChatConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    return _to_conversation_read(conversation)


@router.get("/{conversation_id}/messages", response_model=list[ChatMessageRead])
def get_messages(
    conversation_id: uuid.UUID,
    claims: dict[str, Any] = Depends(get_current_claims),
    service: ChatConversationService = Depends(_get_service),
) -> list[ChatMessageRead]:
    try:
        messages = service.get_messages(conversation_id, _owner_id(claims))
    except ChatConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    return [_to_message_read(message) for message in messages]


@router.post("/{conversation_id}/messages", response_model=ChatSendMessageResponse)
def send_message(
    conversation_id: uuid.UUID,
    payload: ChatSendMessageRequest,
    claims: dict[str, Any] = Depends(get_current_claims),
    groq_client: GroqClient = Depends(get_groq_client),
    db: Session = Depends(get_db),
    service: ChatConversationService = Depends(_get_service),
) -> ChatSendMessageResponse:
    context_builder = SecurityChatContextBuilder(
        device_repository=SqlAlchemyDeviceRepository(db),
        alert_repository=SqlAlchemyAlertRepository(db),
        network_metrics_repository=SqlAlchemyNetworkMetricsRepository(db),
    )
    security_chat_service = SecurityChatService(groq_client, context_builder)
    try:
        reply = service.send_message(conversation_id, _owner_id(claims), payload.message, security_chat_service)
    except ChatConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    except GroqClientError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return ChatSendMessageResponse(reply=reply)
