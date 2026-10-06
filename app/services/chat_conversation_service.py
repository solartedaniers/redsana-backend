import uuid
from dataclasses import dataclass

from app.core.chat_engine import ChatTurn
from app.domain.assistant_reply import mentions_unexpected_dns
from app.domain.chat_topic import UserStartableChatTopic
from app.domain.family_mode import FAMILY_DNS_PRIMARY, FAMILY_DNS_SECONDARY
from app.domain.router_password_guard import contains_password_disclosure
from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.repositories.chat_conversation_repository import ChatConversationRepository
from app.repositories.chat_message_repository import ChatMessageRepository
from app.services.security_briefing_service import BriefingLanguage, SecurityBriefingService
from app.services.security_chat_service import SecurityChatService

# Largo del titulo autogenerado a partir del primer mensaje del usuario.
AUTO_TITLE_MAX_LENGTH = 40

# Aviso (clave i18n del frontend) cuando el usuario escribe una contraseña.
PASSWORD_DISCLOSURE_NOTICE_KEY = "user.securityAssistant.chat.passwordWarning"
# Aviso cuando, en el modo familiar, la respuesta del modelo nombra un DNS distinto
# a los de la guía: los valores correctos salen de la constante, no del modelo.
FAMILY_DNS_CHECK_NOTICE_KEY = "user.securityAssistant.chat.familyDnsCheck"
_FAMILY_DNS_NOTICE_PARAMS = {"primary": FAMILY_DNS_PRIMARY, "secondary": FAMILY_DNS_SECONDARY}


class ChatConversationNotFoundError(Exception):
    pass


class AssessmentNotBriefableError(Exception):
    """Solo se resume la evaluación más reciente del propio usuario."""


@dataclass(frozen=True)
class SendMessageOutcome:
    # reply = respuesta del asistente (None si el mensaje no se procesó, p. ej.
    # traía una contraseña). notice_key = aviso fijo (i18n) que acompaña o
    # reemplaza a la respuesta.
    reply: str | None
    notice_key: str | None
    notice_params: dict[str, str] | None = None


@dataclass(frozen=True)
class AssessmentBriefing:
    conversation: ChatConversation
    messages: list[ChatMessage]


def _auto_title(first_message: str) -> str:
    trimmed = first_message.strip()
    if len(trimmed) <= AUTO_TITLE_MAX_LENGTH:
        return trimmed
    return trimmed[:AUTO_TITLE_MAX_LENGTH].rstrip() + "…"


def _to_turns(messages: list[ChatMessage]) -> list[ChatTurn]:
    return [ChatTurn(message.role, message.content) for message in messages]


class ChatConversationService:
    """Orquesta el historial de conversaciones: persistencia de mensajes +
    auto-titulo, delegando el intercambio con el modelo a SecurityChatService
    y la redacción del resumen inicial a SecurityBriefingService."""

    def __init__(
        self,
        conversation_repository: ChatConversationRepository,
        message_repository: ChatMessageRepository,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._message_repository = message_repository

    def list_conversations(self, owner_id: uuid.UUID) -> list[ChatConversation]:
        return self._conversation_repository.list_by_owner(owner_id)

    def create_conversation(self, owner_id: uuid.UUID, topic: UserStartableChatTopic | None = None) -> ChatConversation:
        return self._conversation_repository.create(owner_id, topic=topic)

    def rename_conversation(self, conversation_id: uuid.UUID, owner_id: uuid.UUID, title: str) -> ChatConversation:
        conversation = self._conversation_repository.update_title(conversation_id, owner_id, title.strip())
        if conversation is None:
            raise ChatConversationNotFoundError(f"Conversation '{conversation_id}' does not exist")
        return conversation

    def get_messages(self, conversation_id: uuid.UUID, owner_id: uuid.UUID) -> list[ChatMessage]:
        self._require_owned_conversation(conversation_id, owner_id)
        return self._message_repository.list_by_conversation(conversation_id)

    def send_message(
        self, conversation_id: uuid.UUID, owner_id: uuid.UUID, text: str, security_chat_service: SecurityChatService
    ) -> SendMessageOutcome:
        conversation = self._require_owned_conversation(conversation_id, owner_id)

        # La contraseña nunca se guarda ni se envía al modelo (un servicio
        # externo): el mensaje se descarta aquí y solo se devuelve el aviso.
        if contains_password_disclosure(text):
            return SendMessageOutcome(reply=None, notice_key=PASSWORD_DISCLOSURE_NOTICE_KEY)

        history = _to_turns(self._message_repository.list_by_conversation(conversation_id))
        self._message_repository.create(conversation_id, "user", text)
        if conversation.title is None:
            self._conversation_repository.update_title(conversation_id, owner_id, _auto_title(text))

        reply = security_chat_service.ask(owner_id, history, text, conversation.topic)

        self._message_repository.create(conversation_id, "assistant", reply)
        self._conversation_repository.touch(conversation_id)
        if conversation.topic == "family_mode" and mentions_unexpected_dns(reply):
            return SendMessageOutcome(reply, FAMILY_DNS_CHECK_NOTICE_KEY, _FAMILY_DNS_NOTICE_PARAMS)
        return SendMessageOutcome(reply=reply, notice_key=None)

    def start_assessment_briefing(
        self,
        owner_id: uuid.UUID,
        assessment_id: uuid.UUID,
        latest_assessment_id: uuid.UUID | None,
        language: BriefingLanguage,
        briefing_service: SecurityBriefingService,
    ) -> AssessmentBriefing:
        """Idempotente: una evaluación tiene a lo sumo un resumen. Si ya existe
        se devuelve tal cual, sin volver a llamar al modelo."""
        if assessment_id != latest_assessment_id:
            raise AssessmentNotBriefableError(f"Assessment '{assessment_id}' is not the owner's latest")

        existing = self._conversation_repository.get_by_assessment(assessment_id, owner_id)
        if existing is not None:
            return AssessmentBriefing(existing, self._message_repository.list_by_conversation(existing.id))

        # Se redacta antes de crear nada: si el modelo falla no queda una
        # conversación vacía ni un mensaje inventado.
        text = briefing_service.write(owner_id, language)
        conversation = self._conversation_repository.create(
            owner_id, topic="assessment_briefing", assessment_id=assessment_id
        )
        message = self._message_repository.create(conversation.id, "assistant", text)
        return AssessmentBriefing(conversation, [message])

    def _require_owned_conversation(self, conversation_id: uuid.UUID, owner_id: uuid.UUID) -> ChatConversation:
        conversation = self._conversation_repository.get_by_id(conversation_id, owner_id)
        if conversation is None:
            raise ChatConversationNotFoundError(f"Conversation '{conversation_id}' does not exist")
        return conversation
