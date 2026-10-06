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


def _to_anomaly_status_read(status: AnomalyStatus) -> AnomalyStatusRead:
    return AnomalyStatusRead(
        status=status.status, samples_collected=status.samples_collected, samples_required=status.samples_required
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
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db), _network_identifier())
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
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db), _network_identifier())
    snapshots = service.get_history(_resolve_target_owner_id(user, user_id), from_, to)
    return [NetworkMetricSampleRead(timestamp=s.recorded_at, latency_ms=s.latency_ms) for s in snapshots]


@router.get("/anomaly-status", response_model=AnomalyStatusRead)
def get_anomaly_status(
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnomalyStatusRead:
    service = NetworkAnomalyService(SqlAlchemyNetworkMetricsRepository(db), SqlAlchemyAlertRepository(db))
    status = service.get_status(_resolve_target_owner_id(user, user_id))
    return _to_anomaly_status_read(status)


def _evaluate_anomalies_in_background(owner_id: uuid.UUID) -> None:
    """Corre después de que la respuesta ya se envió (BackgroundTasks), con su
    propia sesión de DB: la del request (`db: Session = Depends(get_db)`) ya se
    cerró para cuando esto se ejecuta. Entrenar IsolationForest sobre la ventana
    completa (1440 muestras) mide ~200ms -- nada grave para un proceso en
    segundo plano, pero sí perceptible si corriera dentro del request y
    volvería lento un POST que hoy responde en ~160ms."""
    db = SessionLocal()
    try:
        service = NetworkAnomalyService(SqlAlchemyNetworkMetricsRepository(db), SqlAlchemyAlertRepository(db))
        service.evaluate_latest(owner_id)
    finally:
        db.close()


def _evaluate_outage_in_background(owner_id: uuid.UUID) -> None:
    """Mismo motivo que _evaluate_anomalies_in_background (sesión propia, corre
    tras la respuesta); se mantiene como background task separado para no
    acoplar los dos detectores entre sí, aunque este en particular es liviano
    (sin ML, un barrido lineal acotado)."""
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
    db: Session = Depends(get_db),
) -> NetworkMetricSnapshotRead:
    """Registra un snapshot real: el usuario autenticado inserta el suyo; un
    admin puede insertar a nombre de otro usuario (mismo override que /latest
    y /history)."""
    owner_id = _resolve_target_owner_id(user, payload.owner_id)
    service = NetworkMetricsService(SqlAlchemyNetworkMetricsRepository(db), _network_identifier())
    snapshot = service.record_snapshot(owner_id, payload)

    # Evaluación de anomalías y de cortes, desacopladas entre sí y de
    # NetworkMetricsService: el router orquesta, cada detector solo conoce sus
    # propios repositorios. En segundo plano para no sumar latencia al POST.
    background_tasks.add_task(_evaluate_anomalies_in_background, owner_id)
    background_tasks.add_task(_evaluate_outage_in_background, owner_id)

    return _to_snapshot_read(snapshot)
