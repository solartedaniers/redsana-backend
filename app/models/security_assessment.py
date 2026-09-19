import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SecurityAssessment(Base):
    __tablename__ = "security_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Respuestas crudas del usuario ({"default-password": "yes", ...}); el
    # score y las recomendaciones se recalculan en cada lectura desde aquí
    # (ver app/domain/security_assessment.py), nunca se guardan ya calculados.
    answers: Mapped[dict] = mapped_column(JSON, nullable=False)
    wifi_encryption_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # timezone=True: se guarda con offset UTC explícito, para que el frontend
    # pueda convertir correctamente a la hora local del usuario.
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
