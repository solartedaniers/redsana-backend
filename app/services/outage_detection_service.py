import uuid

from app.domain.network_outage import OUTAGE_LOOKBACK_LIMIT, OutageSample, detect_recovered_outage
from app.repositories.alert_repository import AlertRepository
from app.repositories.network_metrics_repository import NetworkMetricsRepository

OUTAGE_ALERT_TYPE = "outage"
OUTAGE_MESSAGE_KEY = "alertsCenter.messages.briefOutage"


class OutageDetectionService:
    """Complementa a NetworkAnomalyService (mismo punto de enganche en el
    router: se llama tras persistir un snapshot nuevo), pero no depende de el
    ni de NetworkMetricsService -- cada detector solo conoce sus propios
    repositorios, igual que el resto del proyecto."""

    def __init__(self, metrics_repository: NetworkMetricsRepository, alert_repository: AlertRepository) -> None:
        self._metrics_repository = metrics_repository
        self._alert_repository = alert_repository

    def evaluate_latest(self, owner_id: uuid.UUID) -> None:
        window = self._metrics_repository.list_latest(owner_id, OUTAGE_LOOKBACK_LIMIT)
        samples: list[OutageSample] = [(snapshot.recorded_at, snapshot.packet_loss_percent) for snapshot in window]

        episode = detect_recovered_outage(samples)
        if episode is None:
            return

        # Sin chequeo de "ya hay una sin reconocer": a diferencia de prediction
        # (condicion en curso), un corte ya recuperado es un evento terminado.
        # La transicion caida->recuperada solo existe una vez por corte -- en
        # la siguiente evaluacion ya no hay transicion que detectar.
        self._alert_repository.create(
            owner_id=owner_id,
            type_=OUTAGE_ALERT_TYPE,
            severity=episode.severity,
            message_key=OUTAGE_MESSAGE_KEY,
            message_params={"minutes": episode.duration_minutes},
            created_at=None,
        )
