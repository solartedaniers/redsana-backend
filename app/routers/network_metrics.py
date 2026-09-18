import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.authorization import ADMIN_ROLE_NAME, get_current_user
from app.core.database import get_db
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.user import User
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.schemas.network_metrics import NetworkMetricSampleRead, NetworkMetricSnapshotCreate, NetworkMetricSnapshotRead
from app.services.network_metrics_service import NetworkMetricsService

router = APIRouter(prefix="/api/network-metrics", tags=["network-metrics"])


def _resolve_target_owner_id(user: User, requested_user_id: uuid.UUID | None) -> uuid.UUID:
    """Un admin puede consultar la red de otro usuario (supervision); cualquier
    otro caso queda scopeado al propio usuario autenticado."""
    if requested_user_id is None or requested_user_id == user.id:
        return user.id
    if user.role.name != ADMIN_ROLE_NAME:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return requested_user_id


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
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NetworkMetricSnapshotRead:
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db))
    snapshot = service.get_latest_snapshot(_resolve_target_owner_id(user, user_id))
    return _to_snapshot_read(snapshot) if snapshot is not None else _default_snapshot_read()


@router.get("/history", response_model=list[NetworkMetricSampleRead])
def get_history(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NetworkMetricSampleRead]:
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db))
    snapshots = service.get_history(_resolve_target_owner_id(user, user_id), from_, to)
    return [NetworkMetricSampleRead(timestamp=s.recorded_at, latency_ms=s.latency_ms) for s in snapshots]


@router.post("", response_model=NetworkMetricSnapshotRead, status_code=201)
def record_snapshot(
    payload: NetworkMetricSnapshotCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NetworkMetricSnapshotRead:
    """Registra un snapshot real: el usuario autenticado inserta el suyo; un
    admin puede insertar a nombre de otro usuario (mismo override que /latest
    y /history)."""
    owner_id = _resolve_target_owner_id(user, payload.owner_id)
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db))
    snapshot = service.record_snapshot(owner_id, payload)
    return _to_snapshot_read(snapshot)
