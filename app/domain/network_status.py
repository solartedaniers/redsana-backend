from dataclasses import dataclass
from typing import Literal

NetworkStatus = Literal["good", "warning", "critical", "unknown"]


@dataclass(frozen=True)
class NetworkStatusThresholds:
    """Desde dónde una medición es advertencia o crítica. Los valores salen de Settings (NETWORK_STATUS_*) y el
    frontend los lee de GET /api/network-metrics/thresholds, así que esta es la única fuente."""

    latency_warning_ms: float
    latency_critical_ms: float
    packet_loss_warning_percent: float
    packet_loss_critical_percent: float


def compute_network_status(
    latency_ms: float, packet_loss_percent: float, thresholds: NetworkStatusThresholds
) -> NetworkStatus:
    if latency_ms >= thresholds.latency_critical_ms or packet_loss_percent >= thresholds.packet_loss_critical_percent:
        return "critical"
    if latency_ms >= thresholds.latency_warning_ms or packet_loss_percent >= thresholds.packet_loss_warning_percent:
        return "warning"
    return "good"
