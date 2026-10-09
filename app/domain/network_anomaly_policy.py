from redsana_ai import ANOMALY_WINDOW_SIZE, DeviatingMetric

from app.domain.alert_messages import alert_message_key
from app.domain.measurement_source import MeasurementSource

# Historial mínimo antes de evaluar. La web casi nunca junta 24 h seguidas, así que empieza con 12 h
# aunque sea menos precisa hasta completar el día.
MIN_SAMPLES_TO_CALIBRATE_BY_SOURCE: dict[MeasurementSource, int] = {
    "native": ANOMALY_WINDOW_SIZE,
    "web": ANOMALY_WINDOW_SIZE // 2,
}

# Clave i18n del Centro de alertas para cada métrica que el detector puede señalar.
ANOMALY_MESSAGE_KEYS: dict[DeviatingMetric, str] = {
    "latency": alert_message_key("latencyDegraded"),
    "jitter": alert_message_key("connectionUnstable"),
    "packet_loss": alert_message_key("packetsBeingLost"),
}
