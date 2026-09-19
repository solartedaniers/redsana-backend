import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat_conversation import ChatConversation
from app.repositories.chat_conversation_repository import ChatConversationRepository


class SqlAlchemyChatConversationRepository(ChatConversationRepository):
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_by_owner(self, owner_id: uuid.UUID) -> list[ChatConversation]:
        stmt = (
            select(ChatConversation)
            .where(ChatConversation.owner_id == owner_id)
            .order_by(ChatConversation.updated_at.desc())
        )
        return list(self._db.scalars(stmt).all())

    def get_by_id(self, conversation_id: uuid.UUID, owner_id: uuid.UUID) -> ChatConversation | None:
        stmt = select(ChatConversation).where(
            ChatConversation.id == conversation_id, ChatConversation.owner_id == owner_id
        )
        return self._db.scalars(stmt).first()

    def create(self, owner_id: uuid.UUID) -> ChatConversation:
        conversation = ChatConversation(owner_id=owner_id)
        self._db.add(conversation)
        self._db.commit()
        self._db.refresh(conversation)
        return conversation

    def update_title(self, conversation_id: uuid.UUID, owner_id: uuid.UUID, title: str) -> ChatConversation | None:
        conversation = self.get_by_id(conversation_id, owner_id)
        if conversation is None:
            return None
        conversation.title = title
        self._db.commit()
        self._db.refresh(conversation)
        return conversation

    def touch(self, conversation_id: uuid.UUID) -> None:
        conversation = self._db.get(ChatConversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = datetime.now(timezone.utc)
            self._db.commit()
