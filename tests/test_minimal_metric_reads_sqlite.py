"""Con los mismos datos fijos en SQLite, leer solo las columnas que se usan da exactamente lo mismo que leer las filas
completas: lo que recibe cada detector, lo que decide y la alerta que guarda."""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.ai_composition import build_local_anomaly_detector, build_local_outage_detector
from app.core.config import get_settings
from app.models.base import Base
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.role import Role
from app.models.user import User
from app.repositories.network_metrics_repository import NetworkMetricsRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.services.network_anomaly_service import NetworkAnomalyService
from app.services.outage_detection_service import OutageDetectionService
from tests.test_alert_service import FakeAlertRepository

OWNER_ID = uuid.uuid4()
HOME_NETWORK = "a" * 64
OFFICE_NETWORK = "b" * 64
START = datetime(2026, 10, 1, tzinfo=UTC)
HOME_SAMPLES = 1500
COOLDOWN = timedelta(minutes=60)


class _FullRowsRepository(SqlAlchemyNetworkMetricsRepository):
    """Lee como antes: filas completas, y de ellas toma lo que usa cada detector."""

    list_latest_vectors = NetworkMetricsRepository.list_latest_vectors
    list_latest_outage_samples = NetworkMetricsRepository.list_latest_outage_samples


class _RecordingOutageDetector:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.windows: list[list] = []
        self.episodes: list = []

    def detect(self, window):
        self.windows.append(list(window))
        episode = self._inner.detect(window)
        self.episodes.append(episode)
        return episode


class _RecordingDetector:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[tuple[list, tuple]] = []
        self.results: list = []

    def evaluate(self, history, latest):
        self.calls.append((list(history), latest))
        result = self._inner.evaluate(history, latest)
        self.results.append(result)
        return result


def _snapshot(minute: int, latency: float, jitter: float, loss: float, source: str, network_id: str | None):
    return NetworkMetricSnapshot(
        owner_id=OWNER_ID,
        recorded_at=START + timedelta(minutes=minute),
        latency_ms=latency,
        jitter_ms=jitter,
        packet_loss_percent=loss,
        status="good",
        source=source,
        network_id=network_id,
        gateway_latency_ms=None if source == "web" else round(1 + minute % 7 * 0.37, 2),
    )


@pytest.fixture()
def session_factory():
    """La red de casa con más de 1440 mediciones del escritorio, mezclada con otra red, la web y una red desconocida;
    la última es una latencia anómala."""
    rng = random.Random(1756)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add_all([Role(id=1, name="standard"), User(id=OWNER_ID, email="owner@example.com", role_id=1)])
        rows = []
        for minute in range(HOME_SAMPLES):
            rows.append(
                _snapshot(
                    minute, rng.gauss(22, 3), abs(rng.gauss(2, 0.5)), rng.choice((0, 0, 0, 1.5)), "native", HOME_NETWORK
                )
            )
            if minute % 3 == 0:
                rows.append(_snapshot(minute, rng.gauss(60, 8), 4.2, 0, "native", OFFICE_NETWORK))
            if minute % 5 == 0:
                rows.append(_snapshot(minute, rng.gauss(90, 10), 9.1, 0, "web", HOME_NETWORK))
            if minute % 11 == 0:
                rows.append(_snapshot(minute, 35.5, 3.3, 0, "native", None))
        rows.append(_snapshot(HOME_SAMPLES, 400.25, 2.125, 0, "native", HOME_NETWORK))
        db.add_all(rows)
        db.commit()
    yield factory
    Base.metadata.drop_all(engine)


def _loaded_snapshots(session_factory, run) -> int:
    loaded: list[object] = []

    def capture(_session, instance) -> None:
        if isinstance(instance, NetworkMetricSnapshot):
            loaded.append(instance)

    event.listen(session_factory, "loaded_as_persistent", capture)
    try:
        run()
    finally:
        event.remove(session_factory, "loaded_as_persistent", capture)
    return len(loaded)


def _evaluate_anomaly(session_factory, repository_class) -> tuple[_RecordingDetector, FakeAlertRepository, int]:
    detector = _RecordingDetector(build_local_anomaly_detector())
    alerts = FakeAlertRepository()
    with session_factory() as db:
        service = NetworkAnomalyService(repository_class(db), alerts, detector, alert_cooldown=COOLDOWN)
        loaded = _loaded_snapshots(session_factory, lambda: service.evaluate_latest(OWNER_ID))
    return detector, alerts, loaded


def _alert_fields(alerts: FakeAlertRepository) -> list[tuple]:
    return [
        (alert.type, alert.severity, alert.message_key, alert.message_params) for alert in alerts.list_all(OWNER_ID)
    ]


def test_the_anomaly_detector_gets_the_same_window_and_raises_the_same_alert(session_factory) -> None:
    before, before_alerts, before_loaded = _evaluate_anomaly(session_factory, _FullRowsRepository)
    after, after_alerts, after_loaded = _evaluate_anomaly(session_factory, SqlAlchemyNetworkMetricsRepository)

    assert after.calls == before.calls
    assert len(after.calls[0][0]) == 1439
    assert after.calls[0][1] == (400.25, 2.125, 0)
    assert after.results == before.results
    assert _alert_fields(after_alerts) == _alert_fields(before_alerts) != []
    # Ahora solo la última medición (get_latest) llega como fila completa; antes, las 1440 de la ventana (que la
    # incluyen).
    assert (before_loaded, after_loaded) == (1440, 1)


def _evaluate_outage(session_factory, repository_class) -> tuple[_RecordingOutageDetector, FakeAlertRepository, int]:
    detector = _RecordingOutageDetector(build_local_outage_detector())
    alerts = FakeAlertRepository()
    with session_factory() as db:
        service = OutageDetectionService(repository_class(db), alerts, detector)
        loaded = _loaded_snapshots(session_factory, lambda: service.evaluate_latest(OWNER_ID))
    return detector, alerts, loaded


def test_the_outage_detector_gets_the_same_samples_and_raises_the_same_alert(session_factory) -> None:
    # Un corte de 6 minutos (en escritorio y web) que se recupera en la última medición.
    with session_factory() as db:
        outage = [_snapshot(HOME_SAMPLES + minute, 0, 0, 100, "native", HOME_NETWORK) for minute in range(1, 7)]
        outage.append(_snapshot(HOME_SAMPLES + 3, 0, 0, 100, "web", HOME_NETWORK))
        outage.append(_snapshot(HOME_SAMPLES + 7, 21.5, 2, 0, "native", HOME_NETWORK))
        db.add_all(outage)
        db.commit()

    before, before_alerts, before_loaded = _evaluate_outage(session_factory, _FullRowsRepository)
    after, after_alerts, after_loaded = _evaluate_outage(session_factory, SqlAlchemyNetworkMetricsRepository)

    lookback = get_settings().outage_lookback_limit
    assert after.windows == before.windows
    assert len(after.windows[0]) == lookback
    assert after.episodes == before.episodes != [None]
    assert _alert_fields(after_alerts) == _alert_fields(before_alerts) != []
    assert (before_loaded, after_loaded) == (lookback, 0)
