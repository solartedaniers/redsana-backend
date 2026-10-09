import uuid
from abc import ABC, abstractmethod

from app.domain.chat_topic import ChatTopic
from app.models.chat_conversation import ChatConversation


class ChatConversationRepository(ABC):

    @abstractmethod
    def list_by_owner(self, owner_id: uuid.UUID) -> list[ChatConversation]:
        """Ordenadas por actividad reciente (updated_at desc), para el historial."""
        ...

    @abstractmethod
    def get_by_id(self, conversation_id: uuid.UUID, owner_id: uuid.UUID) -> ChatConversation | None: ...

    @abstractmethod
    def get_by_assessment(self, assessment_id: uuid.UUID, owner_id: uuid.UUID) -> ChatConversation | None: ...

    @abstractmethod
    def create(
        self, owner_id: uuid.UUID, topic: ChatTopic | None = None, assessment_id: uuid.UUID | None = None
    ) -> ChatConversation: ...

    @abstractmethod
    def update_title(self, conversation_id: uuid.UUID, owner_id: uuid.UUID, title: str) -> ChatConversation | None: ...

    @abstractmethod
    def touch(self, conversation_id: uuid.UUID) -> None:
        """Marca la conversación como recién activa tras cada mensaje para que el historial ordene por actividad."""
        ...
