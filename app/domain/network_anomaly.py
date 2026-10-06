from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Literal

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from app.domain.measurement_source import MeasurementSource

NetworkMetricVector = tuple[float, float, float]  # (latency_ms, jitter_ms, packet_loss_percent)
DeviatingMetric = Literal["latency", "jitter", "packet_loss"]

# A 60s/medición (ver MEASUREMENT_INTERVAL_MS en el frontend), 1440 muestras son
# ~24h: la ventana de entrenamiento cubre un ciclo día/noche completo (la red es
# distinta a las 3am que a las 8pm), para ambas fuentes.
ANOMALY_WINDOW_SIZE = 1440

# Historial mínimo de la misma fuente antes de empezar a evaluar. Escritorio
# mide en segundo plano y llega a 24h sin esfuerzo, así que exige el ciclo
# completo. La web solo mide con la pestaña abierta (24h seguidas es casi
# imposible): empieza con 12h, aceptando menos precisión hasta completar el
# día, porque con medio día visto las horas que el modelo no conoce (p. ej. la
# hora pico nocturna) pueden marcarse como anomalías.
MIN_SAMPLES_TO_CALIBRATE_BY_SOURCE: dict[MeasurementSource, int] = {
    "native": ANOMALY_WINDOW_SIZE,
    "web": ANOMALY_WINDOW_SIZE // 2,
}

# Umbral de desviación (en desviaciones estándar) a partir del cual una anomalía
# ya confirmada por IsolationForest se considera grave en vez de leve.
SEVERITY_CRITICAL_Z_SCORE = 3.0

# contamination='auto' calibra su propio umbral de forma inestable en ventanas
# con poca varianza real (llegó a marcar muestras normales como anómalas en
# pruebas); 0.1 es el valor clásico de la literatura de IsolationForest
# (Liu et al.) y da un umbral estable y predecible.
ISOLATION_FOREST_CONTAMINATION = 0.1


@dataclass(frozen=True)
class DeviationClassification:
    deviating_metric: DeviatingMetric
    severity: Literal["warning", "critical"]
    message_key: str
    message_params: dict[str, float]


_MESSAGE_KEYS: dict[DeviatingMetric, str] = {
    "latency": "alertsCenter.messages.latencyDegraded",
    "jitter": "alertsCenter.messages.connectionUnstable",
    "packet_loss": "alertsCenter.messages.packetsBeingLost",
}


class NetworkAnomalyDetector:
    """Única clase que sabe hablar con IsolationForest/StandardScaler: el resto
    del dominio solo conoce "anómalo o no". Instancia nueva por evaluación (fit
    muta el estado interno del scaler y del bosque, no hay nada que reutilizar
    entre evaluaciones de distintos usuarios o distintos snapshots)."""

    def __init__(self) -> None:
        self._scaler = StandardScaler()
        self._model = IsolationForest(contamination=ISOLATION_FOREST_CONTAMINATION, random_state=42)

    def is_anomalous(self, history: list[NetworkMetricVector], latest: NetworkMetricVector) -> bool:
        """Entrena solo sobre history (la muestra nueva nunca entra a su propio
        baseline) y evalúa si latest se sale del patrón conjunto aprendido."""
        scaled_history = self._scaler.fit_transform(np.array(history))
        self._model.fit(scaled_history)
        scaled_latest = self._scaler.transform([latest])
        prediction = self._model.predict(scaled_latest)
        return bool(prediction[0] == -1)


def classify_deviation(history: list[NetworkMetricVector], latest: NetworkMetricVector) -> DeviationClassification:
    """Decide qué métrica se desvió más (para el mensaje) y qué tan grave es
    (para la severidad), a partir del z-score de cada métrica de latest contra
    la media/desviación de history. Separado de NetworkAnomalyDetector a propósito:
    el modelo decide SI hay anomalía (patrón conjunto), esto decide QUÉ y QUÉ
    TAN GRAVE (comparación simple por métrica, sin jerga estadística de cara
    al usuario -- eso lo traduce el mensaje elegido, no el número en sí)."""
    metrics: tuple[DeviatingMetric, ...] = ("latency", "jitter", "packet_loss")
    z_scores: dict[DeviatingMetric, float] = {}
    typical_values: dict[DeviatingMetric, float] = {}

    for index, metric in enumerate(metrics):
        column = [sample[index] for sample in history]
        average = mean(column)
        deviation = pstdev(column) or 1.0  # evita división por cero si history es constante
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
