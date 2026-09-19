import uuid
from abc import ABC, abstractmethod

from app.models.chat_conversation import ChatConversation


class ChatConversationRepository(ABC):
    """Contrato de acceso a datos para conversaciones del chat, independiente
    de la implementacion concreta."""

    @abstractmethod
    def list_by_owner(self, owner_id: uuid.UUID) -> list[ChatConversation]:
        """Ordenadas por actividad reciente (updated_at desc), para el panel de historial."""
        ...

    @abstractmethod
    def get_by_id(self, conversation_id: uuid.UUID, owner_id: uuid.UUID) -> ChatConversation | None: ...

    @abstractmethod
    def create(self, owner_id: uuid.UUID) -> ChatConversation: ...

    @abstractmethod
    def update_title(self, conversation_id: uuid.UUID, owner_id: uuid.UUID, title: str) -> ChatConversation | None: ...

    @abstractmethod
    def touch(self, conversation_id: uuid.UUID) -> None:
        """Marca la conversacion como recien activa (updated_at = now), llamado
        tras cada mensaje nuevo para que el historial ordene por actividad."""
        ...
