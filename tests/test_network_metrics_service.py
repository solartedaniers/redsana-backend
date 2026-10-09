"""Sin base ni red: cálculo del estado y rango por defecto del historial."""
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.domain.measurement_source import MeasurementSource
from app.domain.network_baseline import BaselineScope
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.network_metrics_repository import NetworkMetricsRepository
from app.schemas.network_metrics import NetworkMetricSnapshotCreate
from app.domain.network_identity import NetworkIdentifier
from app.services.network_metrics_service import NetworkMetricsService


def _in_scope(snapshot: NetworkMetricSnapshot, scope: BaselineScope | None) -> bool:
    return scope is None or (snapshot.source == scope.source and snapshot.network_id == scope.network_id)


class FakeNetworkMetricsRepository(NetworkMetricsRepository):
    def __init__(self) -> None:
        self.snapshots: list[NetworkMetricSnapshot] = []
        self.last_range: tuple[datetime, datetime] | None = None

    def get_latest(self, owner_id: uuid.UUID) -> NetworkMetricSnapshot | None:
        owned = [s for s in self.snapshots if s.owner_id == owner_id]
        return max(owned, key=lambda s: s.recorded_at) if owned else None

    def get_latest_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, NetworkMetricSnapshot]:
        return {
            owner_id: latest
            for owner_id in owner_ids
            if (latest := self.get_latest(owner_id)) is not None
        }

    def list_in_range(self, owner_id: uuid.UUID, start: datetime, end: datetime) -> list[NetworkMetricSnapshot]:
        self.last_range = (start, end)
        return [s for s in self.snapshots if s.owner_id == owner_id and start <= s.recorded_at <= end]

    def list_latest(
        self, owner_id: uuid.UUID, limit: int, scope: BaselineScope | None = None
    ) -> list[NetworkMetricSnapshot]:
        owned = [s for s in self.snapshots if s.owner_id == owner_id and _in_scope(s, scope)]
        return sorted(owned, key=lambda s: s.recorded_at, reverse=True)[:limit]

    def count_by_owner(self, owner_id: uuid.UUID, scope: BaselineScope | None = None) -> int:
        return sum(1 for s in self.snapshots if s.owner_id == owner_id and _in_scope(s, scope))

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
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
        self.snapshots.append(snapshot)
        return snapshot


def _service(repository: NetworkMetricsRepository) -> NetworkMetricsService:
    return NetworkMetricsService(repository, NetworkIdentifier("test-secret"))


def test_get_latest_snapshot_returns_none_without_data() -> None:
    service = _service(FakeNetworkMetricsRepository())

    assert service.get_latest_snapshot(uuid.uuid4()) is None


def test_record_snapshot_computes_status_from_metrics() -> None:
    service = _service(FakeNetworkMetricsRepository())
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
    service = _service(repository)
    before = datetime.now(timezone.utc)

    service.get_history(uuid.uuid4(), start=None, end=None)

    start, end = repository.last_range
    expected_hours = get_settings().network_metrics_default_history_hours
    assert (end - start) == timedelta(hours=expected_hours)
    assert end >= before


FINGERPRINT = "a" * 64


def test_record_snapshot_stores_a_keyed_network_id_never_the_raw_fingerprint() -> None:
    service = _service(FakeNetworkMetricsRepository())
    owner_id = uuid.uuid4()

    snapshot = service.record_snapshot(
        owner_id, NetworkMetricSnapshotCreate(latency_ms=20, jitter_ms=2, packet_loss_percent=0, network_fingerprint=FINGERPRINT)
    )

    assert snapshot.network_id is not None and len(snapshot.network_id) == 64
    assert snapshot.network_id != FINGERPRINT
    # Mismo router y mismo usuario -> misma red; otro usuario u otro secreto -> otra.
    assert NetworkIdentifier("test-secret").network_id(owner_id, FINGERPRINT) == snapshot.network_id
    assert NetworkIdentifier("test-secret").network_id(uuid.uuid4(), FINGERPRINT) != snapshot.network_id
    assert NetworkIdentifier("other-secret").network_id(owner_id, FINGERPRINT) != snapshot.network_id


def test_web_or_unresolved_measurements_have_no_network() -> None:
    snapshot = _service(FakeNetworkMetricsRepository()).record_snapshot(
        uuid.uuid4(), NetworkMetricSnapshotCreate(latency_ms=20, jitter_ms=2, packet_loss_percent=0, source="web")
    )
    assert snapshot.network_id is None


if __name__ == "__main__":
    test_get_latest_snapshot_returns_none_without_data()
    test_record_snapshot_computes_status_from_metrics()
    test_get_history_defaults_to_configured_window_when_no_range_given()
    print("OK")
