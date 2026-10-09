"""Sin base ni red: genera la alerta correcta y, a diferencia de prediction, vuelve a alertar en un segundo corte."""
import uuid
from datetime import datetime, timedelta, timezone

from app.services.outage_detection_service import OutageDetectionService
from tests.test_alert_service import FakeAlertRepository
from tests.test_network_metrics_service import FakeNetworkMetricsRepository


def _seed(repository: FakeNetworkMetricsRepository, owner_id: uuid.UUID, entries: list[tuple[int, float]]) -> None:
    """entries: (minutos atrás, packet_loss_percent)."""
    now = datetime.now(timezone.utc)
    for minutes_ago, loss in entries:
        repository.create(
            owner_id=owner_id,
            latency_ms=0.0 if loss >= 100 else 20.0,
            jitter_ms=0.0,
            packet_loss_percent=loss,
            status="critical" if loss >= 100 else "good",
            source="native",
            recorded_at=now - timedelta(minutes=minutes_ago),
        )


def test_evaluate_latest_creates_an_outage_alert_on_recovery() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed(metrics_repository, owner_id, [(2, 0.0), (1, 100.0), (0, 0.0)])
    service = OutageDetectionService(metrics_repository, alert_repository)

    service.evaluate_latest(owner_id)

    alerts = [a for a in alert_repository.list_all(owner_id) if a.type == "outage"]
    assert len(alerts) == 1
    assert alerts[0].message_key == "user.alertsCenter.messages.briefOutage"
    assert alerts[0].message_params == {"minutes": 1}
    assert alerts[0].severity == "warning"


def test_evaluate_latest_does_nothing_without_an_outage() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed(metrics_repository, owner_id, [(2, 0.0), (1, 0.0), (0, 0.0)])
    service = OutageDetectionService(metrics_repository, alert_repository)

    service.evaluate_latest(owner_id)

    assert alert_repository.list_all(owner_id) == []


def test_a_second_separate_outage_fires_even_with_the_first_alert_unacknowledged() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    service = OutageDetectionService(metrics_repository, alert_repository)

    # Primer corte: se recupera y genera su alerta (queda sin reconocer).
    _seed(metrics_repository, owner_id, [(5, 0.0), (4, 100.0), (3, 0.0)])
    service.evaluate_latest(owner_id)
    assert len(alert_repository.list_all(owner_id)) == 1

    # Segundo corte, separado en el tiempo, también se recupera.
    _seed(metrics_repository, owner_id, [(1, 100.0), (0, 0.0)])
    service.evaluate_latest(owner_id)

    # A diferencia de prediction, esto SÍ genera una segunda alerta: es un evento nuevo.
    outage_alerts = [a for a in alert_repository.list_all(owner_id) if a.type == "outage"]
    assert len(outage_alerts) == 2


if __name__ == "__main__":
    test_evaluate_latest_creates_an_outage_alert_on_recovery()
    test_evaluate_latest_does_nothing_without_an_outage()
    test_a_second_separate_outage_fires_even_with_the_first_alert_unacknowledged()
    print("OK")
