import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.device_role import DEVICE_ROLE_VALUES, DeviceRole
from app.models.base import Base

DEVICE_TRUST_VALUES = ("trusted", "unknown", "blocked")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("owner_id", "mac_address"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mac_address: Mapped[str] = mapped_column(String(17), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    network_role: Mapped[DeviceRole | None] = mapped_column(
        Enum(*DEVICE_ROLE_VALUES, name="device_network_role"), nullable=True
    )
    trust: Mapped[str] = mapped_column(
        Enum(*DEVICE_TRUST_VALUES, name="device_trust"), nullable=False, server_default="unknown"
    )
    # timezone=True: se guarda con offset UTC para que el frontend lo pase bien a la hora local.
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Sin onupdate a propósito: last_seen es la señal de presencia y solo lo mueve un escaneo real.
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
