"""Sin base ni red: los parámetros de los detectores salen de Settings y, por defecto, son exactamente los del paquete."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from redsana_ai import ANOMALY_WINDOW_SIZE, OUTAGE_LOOKBACK_LIMIT, IsolationForestAnomalyDetector, StreakOutageDetector

from app.core import ai_composition
from app.core.config import Settings
from app.services import network_anomaly_service, outage_detection_service
from app.services.network_anomaly_service import NetworkAnomalyService
from app.services.outage_detection_service import OutageDetectionService
from tests.test_ai_composition import _REQUIRED, _use_settings
from tests.test_alert_service import FakeAlertRepository
from tests.test_network_metrics_service import FakeNetworkMetricsRepository


class _LimitSpyRepository(FakeNetworkMetricsRepository):
    def __init__(self) -> None:
        super().__init__()
        self.limits: list[int] = []

    def list_latest(self, owner_id, limit, *args, **kwargs):
        self.limits.append(limit)
        return super().list_latest(owner_id, limit, *args, **kwargs)


def test_by_default_the_detectors_are_identical_to_the_package_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_settings(monkeypatch, groq_api_key="test-groq-key")
    settings = ai_composition.get_settings()

    assert vars(ai_composition.build_local_anomaly_detector()) == vars(IsolationForestAnomalyDetector())
    assert vars(ai_composition.build_local_outage_detector()) == vars(StreakOutageDetector())
    assert settings.anomaly_window_size == ANOMALY_WINDOW_SIZE
    assert settings.outage_lookback_limit == OUTAGE_LOOKBACK_LIMIT
    assert (settings.anomaly_min_samples_for("native"), settings.anomaly_min_samples_for("web")) == (1440, 720)


def test_the_detector_parameters_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "ANOMALY_CONTAMINATION": "0.2",
        "ANOMALY_RANDOM_STATE": "7",
        "ANOMALY_CRITICAL_Z_SCORE": "2.5",
        "OUTAGE_PACKET_LOSS_THRESHOLD_PERCENT": "90",
        "OUTAGE_MAX_GAP_MINUTES": "3",
        "OUTAGE_CRITICAL_DURATION_MINUTES": "10",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None, **_REQUIRED, groq_api_key="test-groq-key")
    monkeypatch.setattr(ai_composition, "get_settings", lambda: settings)

    assert vars(ai_composition.build_local_anomaly_detector()) == vars(
        IsolationForestAnomalyDetector(contamination=0.2, random_state=7, critical_z_score=2.5)
    )
    assert vars(ai_composition.build_local_outage_detector()) == vars(
        StreakOutageDetector(
            packet_loss_threshold_percent=90, max_gap_between_samples=timedelta(minutes=3), critical_duration_minutes=10
        )
    )


def test_the_windows_the_services_read_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANOMALY_WINDOW_SIZE", "100")
    monkeypatch.setenv("OUTAGE_LOOKBACK_LIMIT", "30")
    settings = Settings(_env_file=None, **_REQUIRED, groq_api_key="test-groq-key")
    monkeypatch.setattr(network_anomaly_service, "get_settings", lambda: settings)
    monkeypatch.setattr(outage_detection_service, "get_settings", lambda: settings)
    repository = _LimitSpyRepository()
    owner_id = uuid.uuid4()
    repository.create(
        owner_id=owner_id,
        latency_ms=20,
        jitter_ms=1,
        packet_loss_percent=0,
        status="good",
        source="web",
        recorded_at=datetime.now(UTC),
    )

    NetworkAnomalyService(repository, FakeAlertRepository(), IsolationForestAnomalyDetector()).evaluate_latest(owner_id)
    OutageDetectionService(repository, FakeAlertRepository(), StreakOutageDetector()).evaluate_latest(owner_id)
    status = NetworkAnomalyService(repository, FakeAlertRepository(), IsolationForestAnomalyDetector()).get_status(
        owner_id
    )

    assert repository.limits == [100, 30]
    assert status.samples_required == 50  # la web calibra con la mitad de la ventana


@pytest.mark.parametrize(
    "override",
    [
        {"anomaly_contamination": 0},
        {"anomaly_contamination": 0.6},
        {"anomaly_window_size": 3},
        {"anomaly_critical_z_score": 0},
        {"outage_packet_loss_threshold_percent": 0},
        {"outage_packet_loss_threshold_percent": 101},
        {"outage_max_gap_minutes": 0},
        {"outage_lookback_limit": 1},
        {"outage_critical_duration_minutes": 0},
    ],
)
def test_out_of_range_detector_settings_are_rejected(override: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **_REQUIRED, groq_api_key="test-groq-key", **override)
