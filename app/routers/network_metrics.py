import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.authorization import require_admin
from app.core.database import get_db
from app.core.security import get_current_claims
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.user import User
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.schemas.network_metrics import NetworkMetricSampleRead, NetworkMetricSnapshotCreate, NetworkMetricSnapshotRead
from app.services.network_metrics_service import NetworkMetricsService

router = APIRouter(prefix="/api/network-metrics", tags=["network-metrics"])


def _owner_id(claims: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(claims["sub"])


def _to_snapshot_read(snapshot: NetworkMetricSnapshot) -> NetworkMetricSnapshotRead:
    return NetworkMetricSnapshotRead(
        status=snapshot.status,
        latency_ms=snapshot.latency_ms,
        jitter_ms=snapshot.jitter_ms,
        packet_loss_percent=snapshot.packet_loss_percent,
        updated_at=snapshot.recorded_at,
    )


def _default_snapshot_read() -> NetworkMetricSnapshotRead:
    """Aun no hay mediciones para este usuario: el dashboard necesita un
    estado que pintar en vez de un 404."""
    return NetworkMetricSnapshotRead(
        status="unknown",
        latency_ms=0,
        jitter_ms=0,
        packet_loss_percent=0,
        updated_at=datetime.now(timezone.utc),
    )


@router.get("/latest", response_model=NetworkMetricSnapshotRead)
def get_latest_snapshot(
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> NetworkMetricSnapshotRead:
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db))
    snapshot = service.get_latest_snapshot(_owner_id(claims))
    return _to_snapshot_read(snapshot) if snapshot is not None else _default_snapshot_read()


@router.get("/history", response_model=list[NetworkMetricSampleRead])
def get_history(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> list[NetworkMetricSampleRead]:
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db))
    snapshots = service.get_history(_owner_id(claims), from_, to)
    return [NetworkMetricSampleRead(timestamp=s.recorded_at, latency_ms=s.latency_ms) for s in snapshots]


@router.post("", response_model=NetworkMetricSnapshotRead, status_code=201)
def record_snapshot(
    payload: NetworkMetricSnapshotCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> NetworkMetricSnapshotRead:
    """Endpoint admin para insertar snapshots de prueba, mientras no exista un
    proceso real de medicion (llegara con el modulo de IA)."""
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db))
    snapshot = service.record_snapshot(payload)
    return _to_snapshot_read(snapshot)
