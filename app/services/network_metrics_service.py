import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.domain.network_status import compute_network_status
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.network_metrics_repository import NetworkMetricsRepository
from app.schemas.network_metrics import NetworkMetricSnapshotCreate


class NetworkMetricsService:
    def __init__(self, repository: NetworkMetricsRepository) -> None:
        self._repository = repository

    def get_latest_snapshot(self, owner_id: uuid.UUID) -> NetworkMetricSnapshot | None:
        return self._repository.get_latest(owner_id)

    def get_history(
        self, owner_id: uuid.UUID, start: datetime | None, end: datetime | None
    ) -> list[NetworkMetricSnapshot]:
        range_end = end or datetime.now(timezone.utc)
        default_hours = get_settings().network_metrics_default_history_hours
        range_start = start or (range_end - timedelta(hours=default_hours))
        return self._repository.list_in_range(owner_id, range_start, range_end)

    def record_snapshot(self, payload: NetworkMetricSnapshotCreate) -> NetworkMetricSnapshot:
        status = compute_network_status(payload.latency_ms, payload.packet_loss_percent)
        return self._repository.create(
            owner_id=payload.owner_id,
            latency_ms=payload.latency_ms,
            jitter_ms=payload.jitter_ms,
            packet_loss_percent=payload.packet_loss_percent,
            status=status,
            recorded_at=payload.recorded_at,
        )
