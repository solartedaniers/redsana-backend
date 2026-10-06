import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.chat_topic import ChatTopic, UserStartableChatTopic
from app.domain.user_timezone import MAX_UTC_OFFSET_MINUTES
from app.services.security_briefing_service import BriefingLanguage


class ChatConversationRead(BaseModel):
    id: str
    title: str | None
    # El frontend lo usa como título traducido mientras no haya uno propio.
    topic: ChatTopic | None
    updated_at: datetime


class ChatConversationCreate(BaseModel):
    topic: UserStartableChatTopic | None = None


class ChatConversationRename(BaseModel):
    title: str


class ChatMessageRead(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class ChatSendMessageRequest(BaseModel):
    message: str
    # Date.getTimezoneOffset() del navegador: fechas del contexto en hora local.
    utc_offset_minutes: int = Field(default=0, ge=-MAX_UTC_OFFSET_MINUTES, le=MAX_UTC_OFFSET_MINUTES)


class ChatSendMessageResponse(BaseModel):
    reply: str | None
    # Clave i18n de un aviso fijo: reemplaza a la respuesta si el mensaje no se
    # procesó (contraseña) o la acompaña (DNS distinto al de la guía).
    notice_key: str | None
    notice_params: dict[str, str] | None = None


class ChatBriefingRequest(BaseModel):
    assessment_id: uuid.UUID
    language: BriefingLanguage
    # Date.getTimezoneOffset() del navegador: fechas del contexto en hora local.
    utc_offset_minutes: int = Field(default=0, ge=-MAX_UTC_OFFSET_MINUTES, le=MAX_UTC_OFFSET_MINUTES)


class ChatBriefingRead(BaseModel):
    conversation: ChatConversationRead
    messages: list[ChatMessageRead]
