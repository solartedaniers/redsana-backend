import uuid

from app.domain.device_presence import is_device_online, latest_seen_among
from app.models.alert import Alert
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.alert_repository import AlertRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.network_metrics_repository import NetworkMetricsRepository

# Tope de alertas incluidas en el contexto: evita inflar el prompt si algun dia
# hay decenas de alertas sin reconocer (el modelo solo necesita las mas recientes).
MAX_ALERTS_IN_CONTEXT = 10


class SecurityChatContextBuilder:
    """Junta datos reales del owner (dispositivos, alertas, ultimo snapshot de red)
    y los resume en texto plano para inyectar como contexto del system prompt,
    de forma que el asistente responda con numeros reales en vez de solo explicar
    donde verlos en la app."""

    def __init__(
        self,
        device_repository: DeviceRepository,
        alert_repository: AlertRepository,
        network_metrics_repository: NetworkMetricsRepository,
    ) -> None:
        self._device_repository = device_repository
        self._alert_repository = alert_repository
        self._network_metrics_repository = network_metrics_repository

    def build(self, owner_id: uuid.UUID) -> str:
        devices = self._device_repository.list_by_owner(owner_id)
        latest_seen = latest_seen_among(devices)
        online_count = sum(1 for device in devices if is_device_online(device, latest_seen))

        alerts = self._alert_repository.list_all(owner_id)
        unacknowledged = [alert for alert in alerts if not alert.acknowledged]

        snapshot = self._network_metrics_repository.get_latest(owner_id)

        lines = [
            f"- Dispositivos: {len(devices)} en total, {online_count} en linea ahora mismo.",
            self._alerts_line(unacknowledged),
            self._snapshot_line(snapshot),
        ]
        return "\n".join(lines)

    def _alerts_line(self, unacknowledged: list[Alert]) -> str:
        if not unacknowledged:
            return "- Alertas activas sin reconocer: ninguna."
        summaries = [
            f"[{alert.severity}/{alert.type}] {alert.message_key} {alert.message_params or ''}".strip()
            for alert in unacknowledged[:MAX_ALERTS_IN_CONTEXT]
        ]
        return f"- Alertas activas sin reconocer ({len(unacknowledged)}): " + "; ".join(summaries)

    def _snapshot_line(self, snapshot: NetworkMetricSnapshot | None) -> str:
        if snapshot is None:
            return "- Ultimo snapshot de red: aun no hay ninguno registrado."
        return (
            "- Ultimo snapshot de red: "
            f"latencia {snapshot.latency_ms:.1f} ms, jitter {snapshot.jitter_ms:.1f} ms, "
            f"perdida de paquetes {snapshot.packet_loss_percent:.1f}%, estado '{snapshot.status}'."
        )
