from dataclasses import dataclass
from datetime import datetime, timedelta

OutageSample = tuple[datetime, float]  # (recorded_at, packet_loss_percent)

# Perdida total (los 5 pings de la muestra fallaron) -- no una degradacion
# parcial, eso ya lo cubre el status "critical" normal del dashboard.
OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT = 100.0

# Si el salto entre dos mediciones consecutivas de la racha supera esto, no se
# puede asumir que la app estuvo corriendo (midiendo) todo ese tiempo -- lo mas
# probable es que estuviera cerrada. No se afirma un corte continuo que no se
# puede sostener con evidencia continua (mediciones reales de por medio).
MAX_GAP_BETWEEN_SAMPLES = timedelta(minutes=5)

# Cuantas muestras hacia atras se buscan como maximo para encontrar el inicio
# de una racha de caida (2h a 60s/medicion) -- una racha mas larga que eso
# simplemente se reporta con esta duracion como piso, no como error.
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
    """window: muestras mas recientes primero. Detecta si la mas reciente es
    una recuperacion (perdida < 100%) justo despues de una racha de caidas
    totales con espaciado continuo entre si (ver MAX_GAP_BETWEEN_SAMPLES) --
    si la racha existio pero el hueco hasta la recuperacion es demasiado
    grande, no se reporta (posible cierre de la app en el medio, no un corte
    continuo real)."""
    if len(window) < 2:
        return None

    latest_time, latest_loss = window[0]
    if latest_loss >= OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT:
        return None  # sigue caida, todavia no hay recuperacion que reportar

    previous_time, previous_loss = window[1]
    if previous_loss < OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT:
        return None  # no habia corte, nada que reportar

    if latest_time - previous_time > MAX_GAP_BETWEEN_SAMPLES:
        return None  # la recuperacion no llego "pronto": no se puede afirmar corte continuo

    outage_start_time = previous_time
    for i in range(1, len(window) - 1):
        current_time, _ = window[i]
        older_time, older_loss = window[i + 1]
        if older_loss < OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT or current_time - older_time > MAX_GAP_BETWEEN_SAMPLES:
            break
        outage_start_time = older_time

    duration_minutes = max(1, round((latest_time - outage_start_time).total_seconds() / 60))
    return OutageEpisode(started_at=outage_start_time, recovered_at=latest_time, duration_minutes=duration_minutes)
