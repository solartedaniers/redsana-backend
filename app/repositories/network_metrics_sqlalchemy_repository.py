import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.domain.measurement_source import MeasurementSource
from app.domain.network_baseline import BaselineScope
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

    def get_latest_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, NetworkMetricSnapshot]:
        if not owner_ids:
            return {}
        # ROW_NUMBER particionado por owner: trae solo la fila mas reciente de
        # cada uno en una consulta, no todo el historial de owner_ids grandes.
        rank = (
            func.row_number()
            .over(partition_by=NetworkMetricSnapshot.owner_id, order_by=NetworkMetricSnapshot.recorded_at.desc())
            .label("rank")
        )
        ranked = select(NetworkMetricSnapshot, rank).where(NetworkMetricSnapshot.owner_id.in_(owner_ids)).subquery()
        snapshot = aliased(NetworkMetricSnapshot, ranked)
        stmt = select(snapshot).where(ranked.c.rank == 1)
        return {row.owner_id: row for row in self._db.scalars(stmt).all()}

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

    def list_latest(
        self, owner_id: uuid.UUID, limit: int, scope: BaselineScope | None = None
    ) -> list[NetworkMetricSnapshot]:
        stmt = (
            select(NetworkMetricSnapshot)
            .where(*_owner_filters(owner_id, scope))
            .order_by(NetworkMetricSnapshot.recorded_at.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def count_by_owner(self, owner_id: uuid.UUID, scope: BaselineScope | None = None) -> int:
        stmt = select(func.count()).select_from(NetworkMetricSnapshot).where(*_owner_filters(owner_id, scope))
        return self._db.scalar(stmt) or 0

    def create(
        self,
        owner_id: uuid.UUID,
        latency_ms: float,
        jitter_ms: float,
        packet_loss_percent: float,
        status: str,
        source: MeasurementSource,
        recorded_at: datetime | None,
        network_id: str | None = None,
    ) -> NetworkMetricSnapshot:
        snapshot = NetworkMetricSnapshot(
            owner_id=owner_id,
            latency_ms=latency_ms,
            jitter_ms=jitter_ms,
            packet_loss_percent=packet_loss_percent,
            status=status,
            source=source,
            network_id=network_id,
        )
        if recorded_at is not None:
            snapshot.recorded_at = recorded_at

        self._db.add(snapshot)
        self._db.commit()
        self._db.refresh(snapshot)
        return snapshot


def _owner_filters(owner_id: uuid.UUID, scope: BaselineScope | None) -> list:
    filters = [NetworkMetricSnapshot.owner_id == owner_id]
    if scope is not None:
        filters.append(NetworkMetricSnapshot.source == scope.source)
        # None coincide solo con None (red desconocida), nunca con "cualquier red".
        filters.append(
            NetworkMetricSnapshot.network_id.is_(None)
            if scope.network_id is None
            else NetworkMetricSnapshot.network_id == scope.network_id
        )
    return filters
