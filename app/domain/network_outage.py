from dataclasses import dataclass
from datetime import datetime, timedelta

OutageSample = tuple[datetime, float]  # (recorded_at, packet_loss_percent)

# Pérdida total (los 5 pings fallaron); la degradación parcial ya la cubre el estado "critical".
OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT = 100.0

# Si entre dos mediciones de la racha pasa más que esto, la app probablemente estuvo cerrada y no afirmo un corte continuo.
MAX_GAP_BETWEEN_SAMPLES = timedelta(minutes=5)

# Cuántas muestras hacia atrás busco el inicio de una racha (2 h a una por minuto); más larga se reporta con este piso.
OUTAGE_LOOKBACK_LIMIT = 120

OUTAGE_CRITICAL_DURATION_MINUTES = 15


@dataclass(frozen=True)
class OutageEpisode:
    started_at: datetime
    recovered_at: datetime
    duration_minutes: int

    @property
    def severity(self) -> str:
        return "critical" if self.duration_minutes >= OUTAGE_CRITICAL_DURATION_MINUTES else "warning"


def detect_recovered_outage(window: list[OutageSample]) -> OutageEpisode | None:
    """window va de más nueva a más vieja. Detecta una recuperación justo después de una racha de caídas totales
     continuas; si el hueco es demasiado grande no lo reporto, porque la app pudo estar cerrada."""
    if len(window) < 2:
        return None

    latest_time, latest_loss = window[0]
    if latest_loss >= OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT:
        return None  # sigue caída: todavía no hay recuperación que reportar

    previous_time, previous_loss = window[1]
    if previous_loss < OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT:
        return None  # no había corte, nada que reportar

    if latest_time - previous_time > MAX_GAP_BETWEEN_SAMPLES:
        return None  # la recuperación no llegó pronto: no puedo afirmar un corte continuo

    outage_start_time = previous_time
    for i in range(1, len(window) - 1):
        current_time, _ = window[i]
        older_time, older_loss = window[i + 1]
        if older_loss < OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT or current_time - older_time > MAX_GAP_BETWEEN_SAMPLES:
            break
        outage_start_time = older_time

    duration_minutes = max(1, round((latest_time - outage_start_time).total_seconds() / 60))
    return OutageEpisode(started_at=outage_start_time, recovered_at=latest_time, duration_minutes=duration_minutes)
