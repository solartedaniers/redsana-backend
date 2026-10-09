from dataclasses import dataclass

from app.repositories.alert_repository import AlertRepository
from app.repositories.user_repository import UserRepository
from app.services.network_supervision_service import NetworkSupervisionService

REAL_SCORE_SOURCE = "real"


@dataclass(frozen=True)
class PlatformMetrics:
    total_users: int
    monitored_households: int
    active_alerts: int
    # Promedio SOLO de puntajes reales (del cuestionario); 0 si no hay ninguno, para no cambiar el tipo.
    average_security_score: int
    real_scored_households: int
    unevaluated_households: int


class AdminMetricsService:
    """Junta métricas que ya calculan otros servicios; aquí no se recalcula nada."""

    def __init__(
        self,
        user_repository: UserRepository,
        alert_repository: AlertRepository,
        network_supervision_service: NetworkSupervisionService,
    ) -> None:
        self._user_repository = user_repository
        self._alert_repository = alert_repository
        self._network_supervision_service = network_supervision_service

    def get_platform_metrics(self) -> PlatformMetrics:
        households = self._network_supervision_service.list_households()
        # El estimado mide otra cosa (dispositivos, alertas y red): mezclarlo daba un número que no era ninguno de los dos.
        real_scores = [h.security_score for h in households if h.security_score_source == REAL_SCORE_SOURCE]
        average_score = round(sum(real_scores) / len(real_scores)) if real_scores else 0

        return PlatformMetrics(
            total_users=len(self._user_repository.list_all()),
            monitored_households=len(households),
            active_alerts=self._alert_repository.count_unacknowledged_all(),
            average_security_score=average_score,
            real_scored_households=len(real_scores),
            unevaluated_households=len(households) - len(real_scores),
        )
