from dataclasses import dataclass

from app.repositories.alert_repository import AlertRepository
from app.repositories.user_repository import UserRepository
from app.services.network_supervision_service import NetworkSupervisionService


@dataclass(frozen=True)
class PlatformMetrics:
    total_users: int
    monitored_households: int
    active_alerts: int
    average_security_score: int


class AdminMetricsService:
    """Agrega métricas ya calculadas por otros servicios/repositorios; no
    recalcula nada (usuarios, hogares y security_score ya existen en sus
    propios dominios, solo se combinan aquí para el panel de admin)."""

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
        average_score = round(sum(h.security_score for h in households) / len(households)) if households else 0

        return PlatformMetrics(
            total_users=len(self._user_repository.list_all()),
            monitored_households=len(households),
            active_alerts=self._alert_repository.count_unacknowledged_all(),
            average_security_score=average_score,
        )
