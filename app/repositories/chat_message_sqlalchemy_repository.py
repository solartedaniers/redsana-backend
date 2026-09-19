import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.repositories.chat_message_repository import ChatMessageRepository


class SqlAlchemyChatMessageRepository(ChatMessageRepository):
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_by_conversation(self, conversation_id: uuid.UUID) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return list(self._db.scalars(stmt).all())

    def create(self, conversation_id: uuid.UUID, role: str, content: str) -> ChatMessage:
        message = ChatMessage(conversation_id=conversation_id, role=role, content=content)
        self._db.add(message)
        self._db.commit()
        self._db.refresh(message)
        return message
