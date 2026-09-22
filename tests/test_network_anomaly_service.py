"""Chequeo minimo sin DB/red: valida calibracion, deteccion y deduplicacion
usando los mismos Fake repository que ya usan otros tests de este dominio."""
import uuid
from datetime import datetime, timedelta, timezone

from app.domain.network_anomaly import ANOMALY_WINDOW_SIZE, MIN_SAMPLES_TO_CALIBRATE
from app.services.network_anomaly_service import NetworkAnomalyService
from tests.test_alert_service import FakeAlertRepository
from tests.test_network_metrics_service import FakeNetworkMetricsRepository


def _seed_normal_history(repository: FakeNetworkMetricsRepository, owner_id: uuid.UUID, count: int) -> None:
    base_time = datetime.now(timezone.utc) - timedelta(minutes=count)
    for i in range(count):
        repository.create(
            owner_id=owner_id,
            latency_ms=20.0 + (i % 5) * 0.4,
            jitter_ms=2.0 + (i % 3) * 0.1,
            packet_loss_percent=0.0 + (i % 2) * 0.05,
            status="good",
            recorded_at=base_time + timedelta(minutes=i),
        )


def test_get_status_is_calibrating_below_the_sample_threshold() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, 12)
    service = NetworkAnomalyService(metrics_repository, FakeAlertRepository())

    status = service.get_status(owner_id)

    assert status.status == "calibrating"
    assert status.samples_collected == 12
    assert status.samples_required == MIN_SAMPLES_TO_CALIBRATE


def test_get_status_is_active_once_the_threshold_is_met() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, MIN_SAMPLES_TO_CALIBRATE)
    service = NetworkAnomalyService(metrics_repository, FakeAlertRepository())

    assert service.get_status(owner_id).status == "active"


def test_evaluate_latest_does_nothing_while_calibrating() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, MIN_SAMPLES_TO_CALIBRATE - 1)
    service = NetworkAnomalyService(metrics_repository, alert_repository)

    service.evaluate_latest(owner_id)

    assert alert_repository.list_all(owner_id) == []


def test_evaluate_latest_does_nothing_for_a_normal_sample() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, ANOMALY_WINDOW_SIZE)
    service = NetworkAnomalyService(metrics_repository, alert_repository)

    service.evaluate_latest(owner_id)

    assert alert_repository.list_all(owner_id) == []


def test_evaluate_latest_creates_a_prediction_alert_for_an_anomalous_sample() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, ANOMALY_WINDOW_SIZE - 1)
    metrics_repository.create(
        owner_id=owner_id, latency_ms=400.0, jitter_ms=2.0, packet_loss_percent=0.0, status="critical", recorded_at=None
    )
    service = NetworkAnomalyService(metrics_repository, alert_repository)

    service.evaluate_latest(owner_id)

    alerts = alert_repository.list_all(owner_id)
    assert len(alerts) == 1
    assert alerts[0].type == "prediction"
    assert alerts[0].severity == "critical"
    assert alerts[0].message_key == "alertsCenter.messages.latencyDegraded"


def test_evaluate_latest_does_not_duplicate_an_already_open_alert() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    alert_repository.create(
        owner_id=owner_id,
        type_="prediction",
        severity="critical",
        message_key="alertsCenter.messages.latencyDegraded",
        message_params=None,
        created_at=None,
    )
    _seed_normal_history(metrics_repository, owner_id, ANOMALY_WINDOW_SIZE - 1)
    metrics_repository.create(
        owner_id=owner_id, latency_ms=400.0, jitter_ms=2.0, packet_loss_percent=0.0, status="critical", recorded_at=None
    )
    service = NetworkAnomalyService(metrics_repository, alert_repository)

    service.evaluate_latest(owner_id)

    # Sigue habiendo solo la alerta original: la nueva evaluacion no agrego otra.
    assert len(alert_repository.list_all(owner_id)) == 1


if __name__ == "__main__":
    test_get_status_is_calibrating_below_the_sample_threshold()
    test_get_status_is_active_once_the_threshold_is_met()
    test_evaluate_latest_does_nothing_while_calibrating()
    test_evaluate_latest_does_nothing_for_a_normal_sample()
    test_evaluate_latest_creates_a_prediction_alert_for_an_anomalous_sample()
    test_evaluate_latest_does_not_duplicate_an_already_open_alert()
    print("OK")
