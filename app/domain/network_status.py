from typing import Literal

NetworkStatus = Literal["good", "warning", "critical", "unknown"]

LATENCY_WARNING_MS = 80
LATENCY_CRITICAL_MS = 150
PACKET_LOSS_WARNING_PERCENT = 1
PACKET_LOSS_CRITICAL_PERCENT = 5


def compute_network_status(latency_ms: float, packet_loss_percent: float) -> NetworkStatus:
    """Copia a propósito de latency-severity.ts del frontend: si cambian los umbrales allá, cámbialos aquí."""
    if latency_ms >= LATENCY_CRITICAL_MS or packet_loss_percent >= PACKET_LOSS_CRITICAL_PERCENT:
        return "critical"
    if latency_ms >= LATENCY_WARNING_MS or packet_loss_percent >= PACKET_LOSS_WARNING_PERCENT:
        return "warning"
    return "good"
