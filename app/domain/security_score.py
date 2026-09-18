from app.domain.network_status import NetworkStatus

MAX_DEVICE_TRUST_POINTS = 50
MAX_ALERT_POINTS = 30
MAX_NETWORK_STATUS_POINTS = 20
POINTS_LOST_PER_UNACKNOWLEDGED_ALERT = 10

# El status ya viene calculado (compute_network_status): aqui solo se traduce a
# puntaje, no se reimplementan los umbrales de latencia/perdida de paquetes.
NETWORK_STATUS_POINTS: dict[NetworkStatus, int] = {
    "good": MAX_NETWORK_STATUS_POINTS,
    "warning": MAX_NETWORK_STATUS_POINTS // 2,
    "unknown": MAX_NETWORK_STATUS_POINTS // 2,
    "critical": 0,
}


def compute_security_score(
    trusted_device_ratio: float | None,
    unacknowledged_alert_count: int,
    network_status: NetworkStatus,
) -> int:
    """Proxy temporal del puntaje de seguridad por hogar para el panel de admin,
    mientras security-assistant (cuestionario) no persista evaluaciones reales
    en el backend -- hoy vive solo en el frontend, mockeado. Combina señales
    que si son reales hoy: confianza de dispositivos, alertas sin reconocer y
    el estado de red ya calculado. Reemplazar por el score real de
    security-assistant cuando ese dominio tenga persistencia propia.
    """
    device_points = (
        MAX_DEVICE_TRUST_POINTS
        if trusted_device_ratio is None
        else round(trusted_device_ratio * MAX_DEVICE_TRUST_POINTS)
    )
    alert_points = max(
        0, MAX_ALERT_POINTS - unacknowledged_alert_count * POINTS_LOST_PER_UNACKNOWLEDGED_ALERT
    )
    network_points = NETWORK_STATUS_POINTS[network_status]
    return device_points + alert_points + network_points
