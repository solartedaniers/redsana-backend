import uuid

from app.domain.alert_messages import alert_message_key
from app.domain.network_outage import OUTAGE_LOOKBACK_LIMIT, OutageSample, detect_recovered_outage
from app.repositories.alert_repository import AlertRepository
from app.repositories.network_metrics_repository import NetworkMetricsRepository

OUTAGE_ALERT_TYPE = "outage"
OUTAGE_MESSAGE_KEY = alert_message_key("briefOutage")


class OutageDetectionService:
    """Complementa a NetworkAnomalyService sin depender de él: cada detector conoce solo sus repositorios."""

    def __init__(self, metrics_repository: NetworkMetricsRepository, alert_repository: AlertRepository) -> None:
        self._metrics_repository = metrics_repository
        self._alert_repository = alert_repository

    def evaluate_latest(self, owner_id: uuid.UUID) -> None:
        window = self._metrics_repository.list_latest(owner_id, OUTAGE_LOOKBACK_LIMIT)
        samples: list[OutageSample] = [(snapshot.recorded_at, snapshot.packet_loss_percent) for snapshot in window]

        episode = detect_recovered_outage(samples)
        if episode is None:
            return

        # No reviso si ya hay una sin reconocer: un corte recuperado es un evento terminado y la transición ocurre una sola vez.
        self._alert_repository.create(
            owner_id=owner_id,
            type_=OUTAGE_ALERT_TYPE,
            severity=episode.severity,
            message_key=OUTAGE_MESSAGE_KEY,
            message_params={"minutes": episode.duration_minutes},
            created_at=None,
        )
