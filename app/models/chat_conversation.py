import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.chat_topic import CHAT_TOPIC_VALUES, ChatTopic
from app.models.base import Base


class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (Index("ix_chat_conversations_owner_updated", "owner_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Null hasta el primer mensaje, que se usa recortado como título; el usuario puede renombrarla.
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    topic: Mapped[ChatTopic | None] = mapped_column(Enum(*CHAT_TOPIC_VALUES, name="chat_topic"), nullable=True)
    # Solo en el resumen de una evaluación; único: un resumen por evaluación.
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security_assessments.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    # timezone=True: se guarda con offset UTC para que el frontend lo pase bien a la hora local.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Se actualiza con cada mensaje para ordenar el historial por actividad y no por creación.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
