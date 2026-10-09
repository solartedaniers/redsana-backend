import uuid
from dataclasses import dataclass
from typing import Literal

from app.domain.measurement_source import DEFAULT_MEASUREMENT_SOURCE
from app.domain.network_baseline import baseline_scope
from app.domain.network_anomaly import (
    ANOMALY_WINDOW_SIZE,
    MIN_SAMPLES_TO_CALIBRATE_BY_SOURCE,
    NetworkAnomalyDetector,
    NetworkMetricVector,
    classify_deviation,
)
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.alert_repository import AlertRepository
from app.repositories.network_metrics_repository import NetworkMetricsRepository

PREDICTION_ALERT_TYPE = "prediction"


@dataclass(frozen=True)
class AnomalyStatus:
    status: Literal["calibrating", "active", "unknown_network"]
    samples_collected: int
    samples_required: int


class NetworkAnomalyService:
    """Une el detector con los repositorios de métricas y alertas; NetworkMetricsService no sabe que esto existe."""

    def __init__(self, metrics_repository: NetworkMetricsRepository, alert_repository: AlertRepository) -> None:
        self._metrics_repository = metrics_repository
        self._alert_repository = alert_repository

    def get_status(self, owner_id: uuid.UUID) -> AnomalyStatus:
        # La calibración es por fuente: informo la de la fuente con la que el usuario mide ahora.
        latest = self._metrics_repository.get_latest(owner_id)
        source = latest.source if latest is not None else DEFAULT_MEASUREMENT_SOURCE
        required = MIN_SAMPLES_TO_CALIBRATE_BY_SOURCE[source]
        if latest is None:
            return AnomalyStatus(status="calibrating", samples_collected=0, samples_required=required)
        # La calibración es por red: el progreso es el de la red de la última medición.
        scope = baseline_scope(latest.source, latest.network_id)
        if scope is None:
            return AnomalyStatus(status="unknown_network", samples_collected=0, samples_required=required)
        collected = self._metrics_repository.count_by_owner(owner_id, scope)
        status: Literal["calibrating", "active"] = "active" if collected >= required else "calibrating"
        return AnomalyStatus(status=status, samples_collected=min(collected, required), samples_required=required)

    def evaluate_latest(self, owner_id: uuid.UUID) -> None:
        """Se llama tras guardar un snapshot. Solo entrena con la misma fuente: la latencia web es mayor que el ping
         nativo y mezclarlas haría parecer anómala cada medición web."""
        latest = self._metrics_repository.get_latest(owner_id)
        if latest is None:
            return
        # Solo historial de la misma red: lo normal en otra red parecería anomalía aquí.
        scope = baseline_scope(latest.source, latest.network_id)
        if scope is None:
            return
        window = self._metrics_repository.list_latest(owner_id, ANOMALY_WINDOW_SIZE, scope)
        if len(window) < MIN_SAMPLES_TO_CALIBRATE_BY_SOURCE[latest.source]:
            return

        latest_snapshot, *history_snapshots = window  # window viene de más nueva a más vieja
        latest_vector = _to_vector(latest_snapshot)
        history_vectors: list[NetworkMetricVector] = [_to_vector(snapshot) for snapshot in history_snapshots]

        if not NetworkAnomalyDetector().is_anomalous(history_vectors, latest_vector):
            return

        # Si ya hay una alerta de este tipo sin reconocer no creo otra, o habría una por minuto mientras siga el problema.
        if self._alert_repository.get_latest_unacknowledged(owner_id, PREDICTION_ALERT_TYPE) is not None:
            return

        classification = classify_deviation(history_vectors, latest_vector)
        self._alert_repository.create(
            owner_id=owner_id,
            type_=PREDICTION_ALERT_TYPE,
            severity=classification.severity,
            message_key=classification.message_key,
            message_params=classification.message_params,
            created_at=None,
        )


def _to_vector(snapshot: NetworkMetricSnapshot) -> NetworkMetricVector:
    return (snapshot.latency_ms, snapshot.jitter_ms, snapshot.packet_loss_percent)
