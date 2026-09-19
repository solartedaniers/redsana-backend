import uuid
from abc import ABC, abstractmethod

from app.models.chat_message import ChatMessage


class ChatMessageRepository(ABC):
    """Contrato de acceso a datos para mensajes de una conversacion, independiente
    de la implementacion concreta."""

    @abstractmethod
    def list_by_conversation(self, conversation_id: uuid.UUID) -> list[ChatMessage]:
        """Ordenados cronologicamente (created_at asc), para reconstruir el hilo."""
        ...

    @abstractmethod
    def create(self, conversation_id: uuid.UUID, role: str, content: str) -> ChatMessage: ...
