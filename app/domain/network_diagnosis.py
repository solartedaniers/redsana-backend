from dataclasses import dataclass
from typing import Literal

from app.domain.network_status import NetworkStatus

# router: el problema está entre el equipo y el router (WiFi o router); provider: el router responde bien pero
# internet no; ok: todo bien.
NetworkDiagnosis = Literal["router", "provider", "ok"]

_INTERNET_DEGRADED: frozenset[NetworkStatus] = frozenset({"warning", "critical"})


@dataclass(frozen=True)
class NetworkDiagnosisPolicy:
    """Única fuente de la regla router / proveedor y de la pista de dispositivo saturando. Sin latencia al router
    (la web, el instalador 0.1.5 o un router que no responde al ping) no se diagnostica nada."""

    gateway_latency_bad_ms: float
    busy_device_min_count: int

    def diagnose(self, internet_status: NetworkStatus, gateway_latency_ms: float | None) -> NetworkDiagnosis | None:
        if gateway_latency_ms is None:
            return None
        if gateway_latency_ms >= self.gateway_latency_bad_ms:
            return "router"
        return "provider" if internet_status in _INTERNET_DEGRADED else "ok"

    def possible_busy_device(self, gateway_latency_ms: float | None, connected_devices: int) -> bool | None:
        """Solo una posibilidad: la latencia al router subió y hay muchos equipos conectados. Nunca un hecho."""
        if gateway_latency_ms is None:
            return None
        return gateway_latency_ms >= self.gateway_latency_bad_ms and connected_devices >= self.busy_device_min_count
