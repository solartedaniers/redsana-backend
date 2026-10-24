from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.domain.network_status import NetworkStatus

# router: el problema está entre el equipo y el router (WiFi o router); router_unreachable: internet caído y el router,
# que respondía hace poco, dejó de responder; provider: el router responde bien pero internet no; ok: todo bien.
NetworkDiagnosis = Literal["router", "router_unreachable", "provider", "ok"]

_INTERNET_DEGRADED: frozenset[NetworkStatus] = frozenset({"warning", "critical"})
# Internet caído: se perdieron todos los pings de la medición.
INTERNET_DOWN_LOSS_PERCENT = 100


@dataclass(frozen=True)
class NetworkDiagnosisPolicy:
    """Única fuente de la regla router / proveedor y de la pista de dispositivo saturando. El escritorio la replica
    para diagnosticar sin conexión: la tabla de paridad (tests/fixtures/network_diagnosis_cases.json) obliga a que las
    dos den lo mismo. Sin latencia al router (la web, el instalador 0.1.5 o un router que no responde al ping) no se
    diagnostica nada, salvo que internet esté caído y el router haya respondido hace poco."""

    gateway_latency_bad_ms: float
    busy_device_min_count: int
    gateway_recent_reply_window: timedelta

    def diagnose(
        self,
        internet_status: NetworkStatus,
        gateway_latency_ms: float | None,
        *,
        packet_loss_percent: float = 0,
        router_replied_recently: bool = False,
    ) -> NetworkDiagnosis | None:
        if gateway_latency_ms is None:
            # Un router que nunca responde al ping puede tenerlo bloqueado: sin respuestas recientes no se acusa.
            internet_down = packet_loss_percent >= INTERNET_DOWN_LOSS_PERCENT
            return "router_unreachable" if internet_down and router_replied_recently else None
        if gateway_latency_ms >= self.gateway_latency_bad_ms:
            return "router"
        return "provider" if internet_status in _INTERNET_DEGRADED else "ok"

    def router_replied_recently(self, last_reply_at: datetime | None, measured_at: datetime) -> bool:
        """Cuenta desde la hora de la medición, no desde ahora: una medición que llega tarde se juzga en su momento."""
        return last_reply_at is not None and measured_at - last_reply_at <= self.gateway_recent_reply_window

    def possible_busy_device(self, gateway_latency_ms: float | None, connected_devices: int) -> bool | None:
        """Solo una posibilidad: la latencia al router subió y hay muchos equipos conectados. Nunca un hecho."""
        if gateway_latency_ms is None:
            return None
        return gateway_latency_ms >= self.gateway_latency_bad_ms and connected_devices >= self.busy_device_min_count
