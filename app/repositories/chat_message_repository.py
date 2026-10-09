import uuid
from abc import ABC, abstractmethod

from app.models.chat_message import ChatMessage


class ChatMessageRepository(ABC):

    @abstractmethod
    def list_by_conversation(self, conversation_id: uuid.UUID) -> list[ChatMessage]:
        """Ordenados cronológicamente (created_at asc) para reconstruir el hilo."""
        ...

    @abstractmethod
    def create(self, conversation_id: uuid.UUID, role: str, content: str) -> ChatMessage: ...
