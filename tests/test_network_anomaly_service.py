"""Sin base ni red: calibración, detección y deduplicación con los repositorios falsos de siempre."""

import uuid
from datetime import UTC, datetime, timedelta, timezone

from redsana_ai import ANOMALY_WINDOW_SIZE, IsolationForestAnomalyDetector

from app.core.config import get_settings
from app.domain.measurement_source import MeasurementSource
from app.services.network_anomaly_service import NetworkAnomalyService
from tests.test_alert_service import FakeAlertRepository
from tests.test_network_metrics_service import FakeNetworkMetricsRepository

MIN_NATIVE_SAMPLES = get_settings().anomaly_min_samples_for("native")

HOME_NETWORK = "home-network-id"
OFFICE_NETWORK = "office-network-id"


def _seed_normal_history(
    repository: FakeNetworkMetricsRepository,
    owner_id: uuid.UUID,
    count: int,
    source: MeasurementSource = "native",
    network_id: str | None = HOME_NETWORK,
    minutes_ago: int = 0,
) -> None:
    """Por defecto, historial nativo de una red conocida (la web no tiene red)."""
    network_id = None if source == "web" else network_id
    base_time = datetime.now(timezone.utc) - timedelta(minutes=count + minutes_ago)
    for i in range(count):
        repository.create(
            owner_id=owner_id,
            latency_ms=20.0 + (i % 5) * 0.4,
            jitter_ms=2.0 + (i % 3) * 0.1,
            packet_loss_percent=0.0 + (i % 2) * 0.05,
            status="good",
            source=source,
            network_id=network_id,
            recorded_at=base_time + timedelta(minutes=i),
        )


def test_get_status_is_calibrating_below_the_sample_threshold() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, 12)
    service = NetworkAnomalyService(metrics_repository, FakeAlertRepository(), IsolationForestAnomalyDetector())

    status = service.get_status(owner_id)

    assert status.status == "calibrating"
    assert status.samples_collected == 12
    assert status.samples_required == MIN_NATIVE_SAMPLES


def test_get_status_is_active_once_the_threshold_is_met() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, MIN_NATIVE_SAMPLES)
    service = NetworkAnomalyService(metrics_repository, FakeAlertRepository(), IsolationForestAnomalyDetector())

    assert service.get_status(owner_id).status == "active"


def test_evaluate_latest_does_nothing_while_calibrating() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, MIN_NATIVE_SAMPLES - 1)
    service = NetworkAnomalyService(metrics_repository, alert_repository, IsolationForestAnomalyDetector())

    service.evaluate_latest(owner_id)

    assert alert_repository.list_all(owner_id) == []


def test_evaluate_latest_does_nothing_for_a_normal_sample() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, ANOMALY_WINDOW_SIZE)
    service = NetworkAnomalyService(metrics_repository, alert_repository, IsolationForestAnomalyDetector())

    service.evaluate_latest(owner_id)

    assert alert_repository.list_all(owner_id) == []


def test_evaluate_latest_creates_a_prediction_alert_for_an_anomalous_sample() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, ANOMALY_WINDOW_SIZE - 1)
    metrics_repository.create(
        owner_id=owner_id,
        latency_ms=400.0,
        jitter_ms=2.0,
        packet_loss_percent=0.0,
        status="critical",
        source="native",
        network_id=HOME_NETWORK,
        recorded_at=None,
    )
    service = NetworkAnomalyService(metrics_repository, alert_repository, IsolationForestAnomalyDetector())

    service.evaluate_latest(owner_id)

    alerts = alert_repository.list_all(owner_id)
    assert len(alerts) == 1
    assert alerts[0].type == "prediction"
    assert alerts[0].severity == "critical"
    assert alerts[0].message_key == "user.alertsCenter.messages.latencyDegraded"


COOLDOWN = timedelta(minutes=60)


def _anomalous_setup(previous_alert_age: timedelta | None, acknowledged: bool = False):
    """Historial normal más una medición anómala; opcionalmente, un aviso anterior creado hace previous_alert_age."""
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    if previous_alert_age is not None:
        previous = alert_repository.create(
            owner_id=owner_id,
            type_="prediction",
            severity="critical",
            message_key="user.alertsCenter.messages.latencyDegraded",
            message_params=None,
            created_at=datetime.now(UTC) - previous_alert_age,
        )
        if acknowledged:
            alert_repository.acknowledge(previous.id, owner_id)
    _seed_normal_history(metrics_repository, owner_id, ANOMALY_WINDOW_SIZE - 1)
    metrics_repository.create(
        owner_id=owner_id,
        latency_ms=400.0,
        jitter_ms=2.0,
        packet_loss_percent=0.0,
        status="critical",
        source="native",
        network_id=HOME_NETWORK,
        recorded_at=None,
    )
    service = NetworkAnomalyService(
        metrics_repository, alert_repository, IsolationForestAnomalyDetector(), alert_cooldown=COOLDOWN
    )
    return service, alert_repository, owner_id


def test_evaluate_latest_does_not_repeat_an_alert_within_the_window() -> None:
    service, alert_repository, owner_id = _anomalous_setup(previous_alert_age=timedelta(minutes=10))

    service.evaluate_latest(owner_id)

    assert len(alert_repository.list_all(owner_id)) == 1


def test_an_alert_marked_as_seen_still_blocks_a_repeat_within_the_window() -> None:
    service, alert_repository, owner_id = _anomalous_setup(timedelta(minutes=10), acknowledged=True)

    service.evaluate_latest(owner_id)

    assert len(alert_repository.list_all(owner_id)) == 1


def test_evaluate_latest_repeats_the_alert_once_the_window_has_passed() -> None:
    service, alert_repository, owner_id = _anomalous_setup(previous_alert_age=COOLDOWN + timedelta(minutes=1))

    service.evaluate_latest(owner_id)

    alerts = alert_repository.list_all(owner_id)
    assert len(alerts) == 2
    assert alerts[0].acknowledged is False


def test_an_unseen_alert_older_than_the_window_no_longer_blocks_a_new_one() -> None:
    # Antes, un aviso sin marcar como visto bloqueaba todos los siguientes para siempre.
    service, alert_repository, owner_id = _anomalous_setup(previous_alert_age=timedelta(days=2))

    service.evaluate_latest(owner_id)

    assert len(alert_repository.list_all(owner_id)) == 2


def test_the_window_comes_from_the_environment(monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("PREDICTION_ALERT_COOLDOWN_MINUTES", "5")
    get_settings.cache_clear()
    try:
        service = NetworkAnomalyService(
            FakeNetworkMetricsRepository(), FakeAlertRepository(), IsolationForestAnomalyDetector()
        )
    finally:
        get_settings.cache_clear()

    assert service._alert_cooldown == timedelta(minutes=5)


def test_evaluate_latest_ignores_history_from_another_source() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, ANOMALY_WINDOW_SIZE, source="native")
    # Latencia web normal (~2x el ping): contra el historial nativo se vería anómala.
    metrics_repository.create(
        owner_id=owner_id,
        latency_ms=45.0,
        jitter_ms=2.0,
        packet_loss_percent=0.0,
        status="good",
        source="web",
        recorded_at=None,
    )
    service = NetworkAnomalyService(metrics_repository, alert_repository, IsolationForestAnomalyDetector())

    service.evaluate_latest(owner_id)

    # La fuente web aún está calibrando: no se evalúa contra el historial nativo.
    assert alert_repository.list_all(owner_id) == []
    assert service.get_status(owner_id).status == "calibrating"


def test_web_source_calibrates_with_half_a_day_while_desktop_still_needs_the_full_day() -> None:
    web_required = get_settings().anomaly_min_samples_for("web")
    assert web_required == 720 and MIN_NATIVE_SAMPLES == 1440
    metrics_repository = FakeNetworkMetricsRepository()
    web_owner, native_owner = uuid.uuid4(), uuid.uuid4()
    _seed_normal_history(metrics_repository, web_owner, web_required, source="web")
    _seed_normal_history(metrics_repository, native_owner, web_required, source="native")
    service = NetworkAnomalyService(metrics_repository, FakeAlertRepository(), IsolationForestAnomalyDetector())

    web_status = service.get_status(web_owner)
    native_status = service.get_status(native_owner)

    assert (web_status.status, web_status.samples_required) == ("active", 720)
    assert (native_status.status, native_status.samples_required) == ("calibrating", 1440)


def test_web_source_detects_anomalies_once_calibrated_with_720_samples() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, get_settings().anomaly_min_samples_for("web"), source="web")
    metrics_repository.create(
        owner_id=owner_id,
        latency_ms=400.0,
        jitter_ms=2.0,
        packet_loss_percent=0.0,
        status="critical",
        source="web",
        recorded_at=None,
    )

    NetworkAnomalyService(metrics_repository, alert_repository, IsolationForestAnomalyDetector()).evaluate_latest(
        owner_id
    )

    assert [alert.type for alert in alert_repository.list_all(owner_id)] == ["prediction"]


def _anomalous_sample(repository: FakeNetworkMetricsRepository, owner_id: uuid.UUID, network_id: str | None) -> None:
    repository.create(
        owner_id=owner_id,
        latency_ms=400.0,
        jitter_ms=2.0,
        packet_loss_percent=0.0,
        status="critical",
        source="native",
        network_id=network_id,
        recorded_at=None,
    )


def test_two_networks_calibrate_separately() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    # Casa ya calibrada; ahora el usuario mide en la oficina con pocas muestras.
    _seed_normal_history(metrics_repository, owner_id, MIN_NATIVE_SAMPLES, network_id=HOME_NETWORK, minutes_ago=200)
    _seed_normal_history(metrics_repository, owner_id, 100, network_id=OFFICE_NETWORK)
    _anomalous_sample(metrics_repository, owner_id, OFFICE_NETWORK)
    service = NetworkAnomalyService(metrics_repository, alert_repository, IsolationForestAnomalyDetector())

    status = service.get_status(owner_id)
    service.evaluate_latest(owner_id)

    # La oficina empieza de cero: no usa el historial de la casa ni alerta todavía.
    assert (status.status, status.samples_collected) == ("calibrating", 101)
    assert alert_repository.list_all(owner_id) == []


def test_returning_to_a_network_resumes_its_own_calibration() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    # 1439 más la medición nueva completan la calibración justo al volver.
    _seed_normal_history(metrics_repository, owner_id, MIN_NATIVE_SAMPLES - 1, network_id=HOME_NETWORK, minutes_ago=300)
    _seed_normal_history(metrics_repository, owner_id, 100, network_id=OFFICE_NETWORK, minutes_ago=50)
    # De vuelta en casa retoma su calibración (las de la oficina no cuentan) y detecta.
    _anomalous_sample(metrics_repository, owner_id, HOME_NETWORK)
    service = NetworkAnomalyService(metrics_repository, alert_repository, IsolationForestAnomalyDetector())

    assert service.get_status(owner_id).status == "active"
    service.evaluate_latest(owner_id)
    assert [alert.type for alert in alert_repository.list_all(owner_id)] == ["prediction"]


def test_unknown_network_is_reported_and_never_evaluated() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    alert_repository = FakeAlertRepository()
    owner_id = uuid.uuid4()
    _seed_normal_history(metrics_repository, owner_id, MIN_NATIVE_SAMPLES, network_id=HOME_NETWORK, minutes_ago=50)
    # Escritorio que no pudo resolver el router (o versión vieja): sin red.
    _anomalous_sample(metrics_repository, owner_id, None)
    service = NetworkAnomalyService(metrics_repository, alert_repository, IsolationForestAnomalyDetector())

    assert service.get_status(owner_id).status == "unknown_network"
    service.evaluate_latest(owner_id)
    assert alert_repository.list_all(owner_id) == []


def test_measurements_without_network_never_count_toward_a_calibration() -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    owner_id = uuid.uuid4()
    # Historial previo a esta función: 1440 mediciones nativas sin red.
    _seed_normal_history(metrics_repository, owner_id, MIN_NATIVE_SAMPLES, network_id=None, minutes_ago=50)
    _seed_normal_history(metrics_repository, owner_id, 10, network_id=HOME_NETWORK)

    status = NetworkAnomalyService(
        metrics_repository, FakeAlertRepository(), IsolationForestAnomalyDetector()
    ).get_status(owner_id)

    assert (status.status, status.samples_collected) == ("calibrating", 10)


if __name__ == "__main__":
    test_get_status_is_calibrating_below_the_sample_threshold()
    test_get_status_is_active_once_the_threshold_is_met()
    test_evaluate_latest_does_nothing_while_calibrating()
    test_evaluate_latest_does_nothing_for_a_normal_sample()
    test_evaluate_latest_creates_a_prediction_alert_for_an_anomalous_sample()
    test_evaluate_latest_does_not_repeat_an_alert_within_the_window()
    test_an_alert_marked_as_seen_still_blocks_a_repeat_within_the_window()
    test_evaluate_latest_repeats_the_alert_once_the_window_has_passed()
    test_an_unseen_alert_older_than_the_window_no_longer_blocks_a_new_one()
    test_evaluate_latest_ignores_history_from_another_source()
    test_web_source_calibrates_with_half_a_day_while_desktop_still_needs_the_full_day()
    test_web_source_detects_anomalies_once_calibrated_with_720_samples()
    test_two_networks_calibrate_separately()
    test_returning_to_a_network_resumes_its_own_calibration()
    test_unknown_network_is_reported_and_never_evaluated()
    test_measurements_without_network_never_count_toward_a_calibration()
    print("OK")
