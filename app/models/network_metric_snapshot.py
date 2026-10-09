import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.measurement_source import DEFAULT_MEASUREMENT_SOURCE, MEASUREMENT_SOURCE_VALUES, MeasurementSource
from app.domain.network_status import NetworkStatus
from app.models.base import Base

NETWORK_STATUS_VALUES = ("good", "warning", "critical", "unknown")


class NetworkMetricSnapshot(Base):
    __tablename__ = "network_metric_snapshots"
    __table_args__ = (
        Index("ix_network_metric_snapshots_owner_recorded", "owner_id", "recorded_at"),
        Index("ix_network_metric_snapshots_owner_source_recorded", "owner_id", "source", "recorded_at"),
        Index(
            "ix_network_metric_snapshots_owner_source_network_recorded", "owner_id", "source", "network_id", "recorded_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # timezone=True: se guarda con offset UTC para que el frontend lo pase bien a la hora local.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    jitter_ms: Mapped[float] = mapped_column(Float, nullable=False)
    packet_loss_percent: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[NetworkStatus] = mapped_column(Enum(*NETWORK_STATUS_VALUES, name="network_status"), nullable=False)
    source: Mapped[MeasurementSource] = mapped_column(
        Enum(*MEASUREMENT_SOURCE_VALUES, name="measurement_source"),
        nullable=False,
        default=DEFAULT_MEASUREMENT_SOURCE,
        server_default=DEFAULT_MEASUREMENT_SOURCE,
    )
    # Red donde se midió (HMAC de la huella del router). None es red desconocida.
    network_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
