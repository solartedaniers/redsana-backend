from app.domain.network_status import NetworkStatus

MAX_DEVICE_TRUST_POINTS = 50
MAX_ALERT_POINTS = 30
MAX_NETWORK_STATUS_POINTS = 20
POINTS_LOST_PER_UNACKNOWLEDGED_ALERT = 10

# El estado ya viene calculado; aquí solo lo traduzco a puntaje sin repetir los umbrales.
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
    """Puntaje aproximado por hogar para el admin, con señales reales; no es el del cuestionario del usuario.
     Queda pendiente decidir si el admin debería leer security_assessment_repository en su lugar."""
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
