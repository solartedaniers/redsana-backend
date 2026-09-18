import uuid
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.network_status import NetworkStatus
from app.models.base import Base

NETWORK_STATUS_VALUES = ("good", "warning", "critical", "unknown")


class NetworkMetricSnapshot(Base):
    __tablename__ = "network_metric_snapshots"
    __table_args__ = (Index("ix_network_metric_snapshots_owner_recorded", "owner_id", "recorded_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    jitter_ms: Mapped[float] = mapped_column(Float, nullable=False)
    packet_loss_percent: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[NetworkStatus] = mapped_column(Enum(*NETWORK_STATUS_VALUES, name="network_status"), nullable=False)
