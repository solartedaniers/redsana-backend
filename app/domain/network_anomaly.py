from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Literal

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from app.domain.alert_messages import alert_message_key
from app.domain.measurement_source import MeasurementSource

NetworkMetricVector = tuple[float, float, float]  # (latency_ms, jitter_ms, packet_loss_percent)
DeviatingMetric = Literal["latency", "jitter", "packet_loss"]

# A una medición por minuto, 1440 muestras son ~24 h: así el entrenamiento cubre un ciclo día/noche completo.
ANOMALY_WINDOW_SIZE = 1440

# Historial mínimo antes de evaluar. La web casi nunca junta 24 h seguidas, así que empieza con 12 h
# aunque sea menos precisa hasta completar el día.
MIN_SAMPLES_TO_CALIBRATE_BY_SOURCE: dict[MeasurementSource, int] = {
    "native": ANOMALY_WINDOW_SIZE,
    "web": ANOMALY_WINDOW_SIZE // 2,
}

# Desviaciones estándar a partir de las cuales una anomalía ya confirmada se considera grave y no leve.
SEVERITY_CRITICAL_Z_SCORE = 3.0

# Con contamination='auto' el umbral era inestable en ventanas de poca varianza; 0.1 es el valor clásico y estable.
ISOLATION_FOREST_CONTAMINATION = 0.1


@dataclass(frozen=True)
class DeviationClassification:
    deviating_metric: DeviatingMetric
    severity: Literal["warning", "critical"]
    message_key: str
    message_params: dict[str, float]


_MESSAGE_KEYS: dict[DeviatingMetric, str] = {
    "latency": alert_message_key("latencyDegraded"),
    "jitter": alert_message_key("connectionUnstable"),
    "packet_loss": alert_message_key("packetsBeingLost"),
}


class NetworkAnomalyDetector:
    """Única clase que conoce IsolationForest y StandardScaler; creo una por evaluación porque fit muta su estado."""

    def __init__(self) -> None:
        self._scaler = StandardScaler()
        self._model = IsolationForest(contamination=ISOLATION_FOREST_CONTAMINATION, random_state=42)

    def is_anomalous(self, history: list[NetworkMetricVector], latest: NetworkMetricVector) -> bool:
        """Entrena solo con history (la muestra nueva nunca entra a su propio baseline) y evalúa latest."""
        scaled_history = self._scaler.fit_transform(np.array(history))
        self._model.fit(scaled_history)
        scaled_latest = self._scaler.transform([latest])
        prediction = self._model.predict(scaled_latest)
        return bool(prediction[0] == -1)


def classify_deviation(history: list[NetworkMetricVector], latest: NetworkMetricVector) -> DeviationClassification:
    """Decide qué métrica se desvió más y qué tan grave es con el z-score de cada una.
     El modelo decide SI hay anomalía; esto decide QUÉ fue y qué tan grave."""
    metrics: tuple[DeviatingMetric, ...] = ("latency", "jitter", "packet_loss")
    z_scores: dict[DeviatingMetric, float] = {}
    typical_values: dict[DeviatingMetric, float] = {}

    for index, metric in enumerate(metrics):
        column = [sample[index] for sample in history]
        average = mean(column)
        deviation = pstdev(column) or 1.0  # evita dividir por cero si history es constante
        z_scores[metric] = abs(latest[index] - average) / deviation
        typical_values[metric] = average

    deviating_metric = max(metrics, key=lambda metric: z_scores[metric])
    severity: Literal["warning", "critical"] = (
        "critical" if z_scores[deviating_metric] >= SEVERITY_CRITICAL_Z_SCORE else "warning"
    )
    metric_index = metrics.index(deviating_metric)

    return DeviationClassification(
        deviating_metric=deviating_metric,
        severity=severity,
        message_key=_MESSAGE_KEYS[deviating_metric],
        message_params={
            "current": round(latest[metric_index], 1),
            "typical": round(typical_values[deviating_metric], 1),
        },
    )
