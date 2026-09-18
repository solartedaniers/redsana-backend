import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ALERT_TYPE_VALUES = ("outage", "prediction")
ALERT_SEVERITY_VALUES = ("info", "warning", "critical")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_owner_created", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Enum(*ALERT_TYPE_VALUES, name="alert_type"), nullable=False)
    severity: Mapped[str] = mapped_column(Enum(*ALERT_SEVERITY_VALUES, name="alert_severity"), nullable=False)
    message_key: Mapped[str] = mapped_column(String(255), nullable=False)
    message_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
