"""Chequeo minimo sin DB/red: valida el calculo de status y el rango por defecto del historico."""
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.network_metrics_repository import NetworkMetricsRepository
from app.schemas.network_metrics import NetworkMetricSnapshotCreate
from app.services.network_metrics_service import NetworkMetricsService


class FakeNetworkMetricsRepository(NetworkMetricsRepository):
    def __init__(self) -> None:
        self.snapshots: list[NetworkMetricSnapshot] = []
        self.last_range: tuple[datetime, datetime] | None = None

    def get_latest(self, owner_id: uuid.UUID) -> NetworkMetricSnapshot | None:
        owned = [s for s in self.snapshots if s.owner_id == owner_id]
        return max(owned, key=lambda s: s.recorded_at) if owned else None

    def list_in_range(self, owner_id: uuid.UUID, start: datetime, end: datetime) -> list[NetworkMetricSnapshot]:
        self.last_range = (start, end)
        return [s for s in self.snapshots if s.owner_id == owner_id and start <= s.recorded_at <= end]

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
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
        self.snapshots.append(snapshot)
        return snapshot


def test_get_latest_snapshot_returns_none_without_data() -> None:
    service = NetworkMetricsService(FakeNetworkMetricsRepository())

    assert service.get_latest_snapshot(uuid.uuid4()) is None


def test_record_snapshot_computes_status_from_metrics() -> None:
    service = NetworkMetricsService(FakeNetworkMetricsRepository())
    owner_id = uuid.uuid4()

    good = service.record_snapshot(
        owner_id, NetworkMetricSnapshotCreate(latency_ms=20, jitter_ms=2, packet_loss_percent=0)
    )
    critical = service.record_snapshot(
        owner_id, NetworkMetricSnapshotCreate(latency_ms=200, jitter_ms=10, packet_loss_percent=0)
    )

    assert good.status == "good"
    assert critical.status == "critical"
    assert service.get_latest_snapshot(owner_id) is critical


def test_get_history_defaults_to_configured_window_when_no_range_given() -> None:
    repository = FakeNetworkMetricsRepository()
    service = NetworkMetricsService(repository)
    before = datetime.now(timezone.utc)

    service.get_history(uuid.uuid4(), start=None, end=None)

    start, end = repository.last_range
    expected_hours = get_settings().network_metrics_default_history_hours
    assert (end - start) == timedelta(hours=expected_hours)
    assert end >= before


if __name__ == "__main__":
    test_get_latest_snapshot_returns_none_without_data()
    test_record_snapshot_computes_status_from_metrics()
    test_get_history_defaults_to_configured_window_when_no_range_given()
    print("OK")
