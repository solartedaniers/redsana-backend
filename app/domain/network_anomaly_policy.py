from redsana_ai import DeviatingMetric

from app.domain.alert_messages import alert_message_key

# Clave i18n del Centro de alertas para cada métrica que el detector puede señalar.
ANOMALY_MESSAGE_KEYS: dict[DeviatingMetric, str] = {
    "latency": alert_message_key("latencyDegraded"),
    "jitter": alert_message_key("connectionUnstable"),
    "packet_loss": alert_message_key("packetsBeingLost"),
}
