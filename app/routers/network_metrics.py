import uuid
from datetime import UTC, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.ai_composition import build_anomaly_detector, build_outage_detector
from app.core.authorization import ADMIN_ROLE_NAME, get_current_user
from app.core.config import get_settings
from app.domain.measurement_source import DEFAULT_MEASUREMENT_SOURCE, MeasurementSource
from app.domain.measurement_timing import as_utc
from app.domain.network_identity import NetworkIdentifier
from app.core.database import SessionLocal, get_db
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.user import User
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.schemas.network_anomaly import AnomalyStatusRead
from app.schemas.network_metrics import (
    NetworkMetricSampleRead,
    NetworkMetricSnapshotCreate,
    NetworkMetricSnapshotRead,
    NetworkStatusThresholdsRead,
)
from app.services.network_anomaly_service import AnomalyStatus, NetworkAnomalyService
from app.services.network_diagnosis_service import NetworkDiagnosisResult, NetworkDiagnosisService
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


def _to_snapshot_read(
    snapshot: NetworkMetricSnapshot, diagnosis: NetworkDiagnosisResult | None = None
) -> NetworkMetricSnapshotRead:
    return NetworkMetricSnapshotRead(
        status=snapshot.status,
        latency_ms=snapshot.latency_ms,
        jitter_ms=snapshot.jitter_ms,
        packet_loss_percent=snapshot.packet_loss_percent,
        updated_at=snapshot.recorded_at,
        source=snapshot.source,
        gateway_latency_ms=snapshot.gateway_latency_ms,
        diagnosis=diagnosis.diagnosis if diagnosis else None,
        possible_busy_device=diagnosis.possible_busy_device if diagnosis else None,
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


def _get_diagnosis_service(db: Session = Depends(get_db)) -> NetworkDiagnosisService:
    return NetworkDiagnosisService(
        SqlAlchemyDeviceRepository(db), SqlAlchemyNetworkMetricsRepository(db), get_settings().network_diagnosis_policy
    )


def _get_anomaly_service(db: Session = Depends(get_db)) -> NetworkAnomalyService:
    return NetworkAnomalyService(
        SqlAlchemyNetworkMetricsRepository(db), SqlAlchemyAlertRepository(db), build_anomaly_detector()
    )


@router.get("/latest", response_model=NetworkMetricSnapshotRead)
def get_latest_snapshot(
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    service: NetworkMetricsService = Depends(_get_metrics_service),
    diagnosis_service: NetworkDiagnosisService = Depends(_get_diagnosis_service),
) -> NetworkMetricSnapshotRead:
    owner_id = _resolve_target_owner_id(user, user_id)
    snapshot = service.get_latest_snapshot(owner_id)
    if snapshot is None:
        return _default_snapshot_read()
    return _to_snapshot_read(snapshot, diagnosis_service.describe(owner_id, snapshot))


@router.get("/history", response_model=list[NetworkMetricSampleRead])
def get_history(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    service: NetworkMetricsService = Depends(_get_metrics_service),
) -> list[NetworkMetricSampleRead]:
    snapshots = service.get_history(_resolve_target_owner_id(user, user_id), from_, to)
    return [
        NetworkMetricSampleRead(
            timestamp=s.recorded_at, latency_ms=s.latency_ms, packet_loss_percent=s.packet_loss_percent
        )
        for s in snapshots
    ]


@router.get("/thresholds", response_model=NetworkStatusThresholdsRead)
def get_status_thresholds(
    source: MeasurementSource = Query(DEFAULT_MEASUREMENT_SOURCE),
    _user: User = Depends(get_current_user),
) -> NetworkStatusThresholdsRead:
    """Solo lectura: los mismos umbrales con que se calcula el estado de cada medición nueva de esa fuente. Sin
    source responde los del escritorio, como antes (instalador 0.1.5 y web anterior)."""
    settings = get_settings()
    thresholds = settings.network_status_thresholds_for(source)
    return NetworkStatusThresholdsRead(
        latency_warning_ms=thresholds.latency_warning_ms,
        latency_critical_ms=thresholds.latency_critical_ms,
        packet_loss_warning_percent=thresholds.packet_loss_warning_percent,
        packet_loss_critical_percent=thresholds.packet_loss_critical_percent,
        gateway_latency_bad_ms=settings.network_gateway_latency_bad_ms,
        gateway_recent_reply_minutes=settings.network_gateway_recent_reply_minutes,
    )


@router.get("/anomaly-status", response_model=AnomalyStatusRead)
def get_anomaly_status(
    user_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    service: NetworkAnomalyService = Depends(_get_anomaly_service),
) -> AnomalyStatusRead:
    status = service.get_status(_resolve_target_owner_id(user, user_id))
    return _to_anomaly_status_read(status)


def _is_latest(repository: SqlAlchemyNetworkMetricsRepository, owner_id: uuid.UUID, snapshot_id: uuid.UUID) -> bool:
    # Los detectores miran la medición más nueva: si la que llegó es más vieja (fuera de orden), esa ventana ya se
    # evaluó y repetirlo duplicaría alertas.
    latest = repository.get_latest(owner_id)
    return latest is not None and latest.id == snapshot_id


def _evaluate_anomalies_in_background(owner_id: uuid.UUID, snapshot_id: uuid.UUID) -> None:
    """Corre después de responder, con su propia sesión (la del request ya se cerró). Entrenar el modelo tarda ~200 ms y
    haría lento un POST que hoy responde en ~160 ms."""
    db = SessionLocal()
    try:
        repository = SqlAlchemyNetworkMetricsRepository(db)
        if not _is_latest(repository, owner_id, snapshot_id):
            return
        service = NetworkAnomalyService(repository, SqlAlchemyAlertRepository(db), build_anomaly_detector())
        service.evaluate_latest(owner_id)
    finally:
        db.close()


def _evaluate_outage_in_background(owner_id: uuid.UUID, snapshot_id: uuid.UUID) -> None:
    """Igual que _evaluate_anomalies_in_background, pero aparte para no acoplar los dos detectores."""
    db = SessionLocal()
    try:
        repository = SqlAlchemyNetworkMetricsRepository(db)
        if not _is_latest(repository, owner_id, snapshot_id):
            return
        service = OutageDetectionService(repository, SqlAlchemyAlertRepository(db), build_outage_detector())
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
    # Un reenvío de la cola del cliente que ya se guardó responde igual y no vuelve a evaluar nada.
    already_recorded = service.find_already_recorded(owner_id, payload)
    if already_recorded is not None:
        return _to_snapshot_read(already_recorded)
    snapshot = service.record_snapshot(owner_id, payload)
    # Anomalías y cortes desacoplados y en segundo plano para no sumar latencia al POST. Una medición que llega tarde
    # sí registra el corte (con su duración real), pero no avisa ahora de una degradación que ya pasó.
    timing = get_settings().measurement_timing_policy
    if not timing.is_late(as_utc(snapshot.recorded_at), datetime.now(UTC)):
        background_tasks.add_task(_evaluate_anomalies_in_background, owner_id, snapshot.id)
    background_tasks.add_task(_evaluate_outage_in_background, owner_id, snapshot.id)
    return _to_snapshot_read(snapshot)
