import logging
import math
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from redsana_ai import ChatEngineError
from sqlalchemy.orm import Session

from app.ai_gateway.ai_gateway import AiGateway
from app.ai_gateway.ai_service_errors import AiServiceUnavailableError
from app.core.ai_composition import get_ai_gateway
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_claims, owner_id_from_claims
from app.domain.user_timezone import timezone_from_browser_offset
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.chat_conversation_sqlalchemy_repository import SqlAlchemyChatConversationRepository
from app.repositories.chat_message_sqlalchemy_repository import SqlAlchemyChatMessageRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.repositories.security_assessment_sqlalchemy_repository import SqlAlchemySecurityAssessmentRepository
from app.schemas.chat_conversation import (
    ChatBriefingRead,
    ChatBriefingRequest,
    ChatConversationCreate,
    ChatConversationRead,
    ChatConversationRename,
    ChatMessageRead,
    ChatSendMessageRequest,
    ChatSendMessageResponse,
)
from app.services.chat_conversation_service import (
    AssessmentNotBriefableError,
    ChatConversationNotFoundError,
    ChatConversationService,
)
from app.services.network_security_score_service import default_network_security_score_service
from app.services.security_assessment_service import SecurityAssessmentService
from app.services.security_assistant_service import SecurityAssistantService
from app.services.security_chat_context_service import SecurityChatContextBuilder

logger = logging.getLogger(__name__)
CHAT_ENGINE_UNAVAILABLE_DETAIL = "Chat engine unavailable"
# Lo lee el frontend para mostrar "IA encendiendo" en vez de un error.
AI_WARMING_UP_DETAIL = "ai_warming_up"

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _to_conversation_read(conversation: ChatConversation) -> ChatConversationRead:
    return ChatConversationRead(
        id=str(conversation.id), title=conversation.title, topic=conversation.topic, updated_at=conversation.updated_at
    )


def _to_message_read(message: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(
        id=str(message.id), role=message.role, content=message.content, created_at=message.created_at
    )


def _chat_engine_unavailable(error: ChatEngineError) -> HTTPException:
    # El detalle real de Groq queda en el log del servidor: devolverlo exponía datos internos del proveedor.
    logger.warning("chat engine failed: %s", error)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=CHAT_ENGINE_UNAVAILABLE_DETAIL)


def _ai_warming_up(error: AiServiceUnavailableError) -> HTTPException:
    # El servicio de IA está dormido o arrancando en Render: no es un error para el usuario, solo hay que esperar.
    logger.info("AI service still warming up: %s", error)
    retry_after = math.ceil(get_settings().ai_service_warm_up_poll_seconds)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=AI_WARMING_UP_DETAIL,
        headers={"Retry-After": str(retry_after)},
    )


def _assessment_service(db: Session) -> SecurityAssessmentService:
    return SecurityAssessmentService(SqlAlchemySecurityAssessmentRepository(db), default_network_security_score_service())


def _build_assistant(gateway: AiGateway, db: Session, utc_offset_minutes: int) -> SecurityAssistantService:
    return SecurityAssistantService(
        gateway.security_chat(),
        gateway.security_briefing(),
        SecurityChatContextBuilder(
            device_repository=SqlAlchemyDeviceRepository(db),
            alert_repository=SqlAlchemyAlertRepository(db),
            network_metrics_repository=SqlAlchemyNetworkMetricsRepository(db),
            security_assessment_service=_assessment_service(db),
            user_timezone=timezone_from_browser_offset(utc_offset_minutes),
        )
    )


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
    conversations = service.list_conversations(owner_id_from_claims(claims))
    return [_to_conversation_read(conversation) for conversation in conversations]


@router.post("", response_model=ChatConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ChatConversationCreate | None = None,
    claims: dict[str, Any] = Depends(get_current_claims),
    service: ChatConversationService = Depends(_get_service),
) -> ChatConversationRead:
    conversation = service.create_conversation(owner_id_from_claims(claims), payload.topic if payload else None)
    return _to_conversation_read(conversation)


@router.patch("/{conversation_id}", response_model=ChatConversationRead)
def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ChatConversationRename,
    claims: dict[str, Any] = Depends(get_current_claims),
    service: ChatConversationService = Depends(_get_service),
) -> ChatConversationRead:
    try:
        conversation = service.rename_conversation(conversation_id, owner_id_from_claims(claims), payload.title)
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
        messages = service.get_messages(conversation_id, owner_id_from_claims(claims))
    except ChatConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    return [_to_message_read(message) for message in messages]


@router.post("/{conversation_id}/messages", response_model=ChatSendMessageResponse)
def send_message(
    conversation_id: uuid.UUID,
    payload: ChatSendMessageRequest,
    claims: dict[str, Any] = Depends(get_current_claims),
    gateway: AiGateway = Depends(get_ai_gateway),
    db: Session = Depends(get_db),
    service: ChatConversationService = Depends(_get_service),
) -> ChatSendMessageResponse:
    assistant = _build_assistant(gateway, db, payload.utc_offset_minutes)
    try:
        outcome = service.send_message(conversation_id, owner_id_from_claims(claims), payload.message, assistant)
    except ChatConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    except AiServiceUnavailableError as error:
        raise _ai_warming_up(error) from error
    except ChatEngineError as error:
        raise _chat_engine_unavailable(error) from error
    return ChatSendMessageResponse(
        reply=outcome.reply, notice_key=outcome.notice_key, notice_params=outcome.notice_params
    )


@router.post("/briefings", response_model=ChatBriefingRead)
def start_assessment_briefing(
    payload: ChatBriefingRequest,
    claims: dict[str, Any] = Depends(get_current_claims),
    gateway: AiGateway = Depends(get_ai_gateway),
    db: Session = Depends(get_db),
    service: ChatConversationService = Depends(_get_service),
) -> ChatBriefingRead:
    """Primer mensaje del asistente tras una evaluación; si se pide de nuevo devuelve el mismo sin llamar al modelo."""
    owner_id = owner_id_from_claims(claims)
    latest = _assessment_service(db).get_latest_assessment(owner_id)
    try:
        briefing = service.start_assessment_briefing(
            owner_id,
            payload.assessment_id,
            latest.id if latest else None,
            payload.language,
            _build_assistant(gateway, db, payload.utc_offset_minutes),
        )
    except AssessmentNotBriefableError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found") from error
    except AiServiceUnavailableError as error:
        raise _ai_warming_up(error) from error
    except ChatEngineError as error:
        raise _chat_engine_unavailable(error) from error
    return ChatBriefingRead(
        conversation=_to_conversation_read(briefing.conversation),
        messages=[_to_message_read(message) for message in briefing.messages],
    )
