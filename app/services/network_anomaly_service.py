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
    """Orquesta el detector (dominio puro) con los repositorios de métricas y
    alertas. NetworkMetricsService no sabe que esto existe: la única relación
    entre ambos es que el router llama a los dos servicios por separado."""

    def __init__(self, metrics_repository: NetworkMetricsRepository, alert_repository: AlertRepository) -> None:
        self._metrics_repository = metrics_repository
        self._alert_repository = alert_repository

    def get_status(self, owner_id: uuid.UUID) -> AnomalyStatus:
        # La calibración es por fuente (ver evaluate_latest): se informa la de la
        # fuente con la que el usuario está midiendo ahora mismo.
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
        """Se llama después de persistir un snapshot nuevo. No hace nada si aún
        no hay historial suficiente (calibrando) o si el snapshot no es anómalo.
        Solo entrena con muestras de la misma fuente que la última: la latencia
        web (HTTP) es sistemáticamente mayor que el ping nativo, y mezclarlas
        haría que cada medición web pareciera anómala frente a un historial nativo."""
        latest = self._metrics_repository.get_latest(owner_id)
        if latest is None:
            return
        # Solo historial de la misma red: comparar contra otra red (otro router,
        # otro proveedor) haría que lo normal allá pareciera anomalía aquí.
        scope = baseline_scope(latest.source, latest.network_id)
        if scope is None:
            return
        window = self._metrics_repository.list_latest(owner_id, ANOMALY_WINDOW_SIZE, scope)
        if len(window) < MIN_SAMPLES_TO_CALIBRATE_BY_SOURCE[latest.source]:
            return

        latest_snapshot, *history_snapshots = window  # window viene más nuevo primero
        latest_vector = _to_vector(latest_snapshot)
        history_vectors: list[NetworkMetricVector] = [_to_vector(snapshot) for snapshot in history_snapshots]

        if not NetworkAnomalyDetector().is_anomalous(history_vectors, latest_vector):
            return

        # Ya hay una alerta de este tipo sin reconocer: no duplicar mientras el
        # usuario no la atienda (evita una alerta por minuto si el problema persiste).
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
