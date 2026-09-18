import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.network_metrics_repository import NetworkMetricsRepository


class SqlAlchemyNetworkMetricsRepository(NetworkMetricsRepository):
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_latest(self, owner_id: uuid.UUID) -> NetworkMetricSnapshot | None:
        stmt = (
            select(NetworkMetricSnapshot)
            .where(NetworkMetricSnapshot.owner_id == owner_id)
            .order_by(NetworkMetricSnapshot.recorded_at.desc())
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def list_in_range(self, owner_id: uuid.UUID, start: datetime, end: datetime) -> list[NetworkMetricSnapshot]:
        stmt = (
            select(NetworkMetricSnapshot)
            .where(
                NetworkMetricSnapshot.owner_id == owner_id,
                NetworkMetricSnapshot.recorded_at >= start,
                NetworkMetricSnapshot.recorded_at <= end,
            )
            .order_by(NetworkMetricSnapshot.recorded_at.asc())
        )
        return list(self._db.scalars(stmt).all())

    def create(
        self,
        owner_id: uuid.UUID,
        latency_ms: float,
        jitter_ms: float,
        packet_loss_percent: float,
        status: str,
        recorded_at: datetime | None,
    ) -> NetworkMetricSnapshot:
        snapshot = NetworkMetricSnapshot(
            owner_id=owner_id,
            latency_ms=latency_ms,
            jitter_ms=jitter_ms,
            packet_loss_percent=packet_loss_percent,
            status=status,
        )
        if recorded_at is not None:
            snapshot.recorded_at = recorded_at

        self._db.add(snapshot)
        self._db.commit()
        self._db.refresh(snapshot)
        return snapshot
