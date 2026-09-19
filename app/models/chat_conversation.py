import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (Index("ix_chat_conversations_owner_updated", "owner_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Null hasta el primer mensaje: se autocompleta truncando el primer mensaje
    # del usuario (ver ChatConversationService); el usuario puede renombrarla despues.
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # timezone=True: se guarda con offset UTC explícito, para que el frontend
    # pueda convertir correctamente a la hora local del usuario.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Se actualiza en cada mensaje nuevo (no solo al editar), para ordenar el
    # historial por actividad reciente en vez de por fecha de creación.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
