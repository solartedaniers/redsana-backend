import uuid

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.repositories.chat_conversation_repository import ChatConversationRepository
from app.repositories.chat_message_repository import ChatMessageRepository
from app.services.security_chat_service import SecurityChatService

# Largo del titulo autogenerado a partir del primer mensaje del usuario.
AUTO_TITLE_MAX_LENGTH = 40


class ChatConversationNotFoundError(Exception):
    pass


def _auto_title(first_message: str) -> str:
    trimmed = first_message.strip()
    if len(trimmed) <= AUTO_TITLE_MAX_LENGTH:
        return trimmed
    return trimmed[:AUTO_TITLE_MAX_LENGTH].rstrip() + "…"


class ChatConversationService:
    """Orquesta el historial de conversaciones: persistencia de mensajes +
    auto-titulo, delegando el propio intercambio con Groq a SecurityChatService."""

    def __init__(
        self,
        conversation_repository: ChatConversationRepository,
        message_repository: ChatMessageRepository,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._message_repository = message_repository

    def list_conversations(self, owner_id: uuid.UUID) -> list[ChatConversation]:
        return self._conversation_repository.list_by_owner(owner_id)

    def create_conversation(self, owner_id: uuid.UUID) -> ChatConversation:
        return self._conversation_repository.create(owner_id)

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
    ) -> str:
        conversation = self._require_owned_conversation(conversation_id, owner_id)

        self._message_repository.create(conversation_id, "user", text)
        if conversation.title is None:
            self._conversation_repository.update_title(conversation_id, owner_id, _auto_title(text))

        reply = security_chat_service.ask(owner_id, text)

        self._message_repository.create(conversation_id, "assistant", reply)
        self._conversation_repository.touch(conversation_id)
        return reply

    def _require_owned_conversation(self, conversation_id: uuid.UUID, owner_id: uuid.UUID) -> ChatConversation:
        conversation = self._conversation_repository.get_by_id(conversation_id, owner_id)
        if conversation is None:
            raise ChatConversationNotFoundError(f"Conversation '{conversation_id}' does not exist")
        return conversation
