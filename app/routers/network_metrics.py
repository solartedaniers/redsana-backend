import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.authorization import ADMIN_ROLE_NAME, get_current_user
from app.core.config import get_settings
from app.domain.network_identity import NetworkIdentifier
from app.core.database import SessionLocal, get_db
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.user import User
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.schemas.network_anomaly import AnomalyStatusRead
from app.schemas.network_metrics import NetworkMetricSampleRead, NetworkMetricSnapshotCreate, NetworkMetricSnapshotRead
from app.services.network_anomaly_service import AnomalyStatus, NetworkAnomalyService
from app.services.network_metrics_service import NetworkMetricsService
from app.services.outage_detection_service import OutageDetectionService

router = APIRouter(prefix="/api/network-metrics", tags=["network-metrics"])


def _network_identifier() -> NetworkIdentifier:
    return NetworkIdentifier(get_settings().network_id_secret)


def _resolve_target_owner_id(user: User, requested_user_id: uuid.UUID | None) -> uuid.UUID:
    """Un admin puede consultar la red de otro usuario; en cualquier otro caso se usa el usuario autenticado."""
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


def _to_anomaly_status_read(status: AnomalyStatus) -> AnomalyStatusRead:
    return AnomalyStatusRead(
        status=status.status, samples_collected=status.samples_collected, samples_required=status.samples_required
    )


def _default_snapshot_read() -> NetworkMetricSnapshotRead:
    """Aún no hay mediciones: el dashboard necesita un estado que pintar en vez de un 404."""
    return NetworkMetricSnapshotRead(
        status="unknown",
        latency_ms=0,
        jitter_ms=0,
        packet_loss_percent=0,
        updated_at=datetime.now(timezone.utc),
    )


def _get_metrics_service(db: Session = Depends(get_db)) -> NetworkMetricsService:
    return NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db), _network_identifier())


def _get_anomaly_service(db: Session = Depends(get_db)) -> NetworkAnomalyService:
    return NetworkAnomalyService(SqlAlchemyNetworkMetricsRepository(db), SqlAlchemyAlertRepository(db))


@router.get("/latest", response_model=NetworkMetricSnapshotRead)
def get_latest_snapshot(
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    service: NetworkMetricsService = Depends(_get_metrics_service),
) -> NetworkMetricSnapshotRead:
    snapshot = service.get_latest_snapshot(_resolve_target_owner_id(user, user_id))
    return _to_snapshot_read(snapshot) if snapshot is not None else _default_snapshot_read()


@router.get("/history", response_model=list[NetworkMetricSampleRead])
def get_history(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    service: NetworkMetricsService = Depends(_get_metrics_service),
) -> list[NetworkMetricSampleRead]:
    snapshots = service.get_history(_resolve_target_owner_id(user, user_id), from_, to)
    return [NetworkMetricSampleRead(timestamp=s.recorded_at, latency_ms=s.latency_ms) for s in snapshots]


@router.get("/anomaly-status", response_model=AnomalyStatusRead)
def get_anomaly_status(
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    service: NetworkAnomalyService = Depends(_get_anomaly_service),
) -> AnomalyStatusRead:
    status = service.get_status(_resolve_target_owner_id(user, user_id))
    return _to_anomaly_status_read(status)


def _evaluate_anomalies_in_background(owner_id: uuid.UUID) -> None:
    """Corre después de responder, con su propia sesión (la del request ya se cerró). Entrenar el modelo
     tarda ~200 ms y haría lento un POST que hoy responde en ~160 ms."""
    db = SessionLocal()
    try:
        service = NetworkAnomalyService(SqlAlchemyNetworkMetricsRepository(db), SqlAlchemyAlertRepository(db))
        service.evaluate_latest(owner_id)
    finally:
        db.close()


def _evaluate_outage_in_background(owner_id: uuid.UUID) -> None:
    """Igual que _evaluate_anomalies_in_background, pero aparte para no acoplar los dos detectores."""
    db = SessionLocal()
    try:
        service = OutageDetectionService(SqlAlchemyNetworkMetricsRepository(db), SqlAlchemyAlertRepository(db))
        service.evaluate_latest(owner_id)
    finally:
        db.close()


@router.post("", response_model=NetworkMetricSnapshotRead, status_code=201)
def record_snapshot(
    payload: NetworkMetricSnapshotCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    service: NetworkMetricsService = Depends(_get_metrics_service),
) -> NetworkMetricSnapshotRead:
    """Registra un snapshot real del usuario autenticado; un admin puede registrarlo a nombre de otro."""
    owner_id = _resolve_target_owner_id(user, payload.owner_id)
    snapshot = service.record_snapshot(owner_id, payload)

    # Anomalías y cortes van desacoplados y en segundo plano para no sumar latencia al POST.
    background_tasks.add_task(_evaluate_anomalies_in_background, owner_id)
    background_tasks.add_task(_evaluate_outage_in_background, owner_id)

    return _to_snapshot_read(snapshot)
