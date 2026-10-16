"""Sin red: los detectores en segundo plano usan el servicio solo dentro de la ventana y nunca la renuevan."""
from datetime import datetime, timezone

import pytest
from redsana_ai import (
    AnomalyDetector,
    DeviationClassification,
    NetworkMetricVector,
    OutageDetector,
    OutageEpisode,
    OutageSample,
)

from app.ai_gateway.ai_service_errors import AiServiceUnavailableError
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.windowed_detectors import WindowedAnomalyDetector, WindowedOutageDetector

_CLASSIFICATION = DeviationClassification("latency", "critical", 400.0, 20.8)
_EPISODE = OutageEpisode(
    datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), 3, "warning"
)


class _AnomalyDetector(AnomalyDetector):
    def __init__(self, fails: bool = False) -> None:
        self.calls = 0
        self._fails = fails

    def evaluate(self, history: list[NetworkMetricVector], latest: NetworkMetricVector) -> DeviationClassification | None:
        self.calls += 1
        if self._fails:
            raise AiServiceUnavailableError("asleep")
        return _CLASSIFICATION


class _OutageDetector(OutageDetector):
    def __init__(self, fails: bool = False) -> None:
        self.calls = 0
        self._fails = fails

    def detect(self, window: list[OutageSample]) -> OutageEpisode | None:
        self.calls += 1
        if self._fails:
            raise AiServiceUnavailableError("asleep")
        return _EPISODE


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock()


@pytest.fixture
def usage_window(clock: _FakeClock) -> InteractiveUsageWindow:
    return InteractiveUsageWindow(600, clock)


def test_anomalies_use_the_local_package_while_the_window_is_closed(usage_window: InteractiveUsageWindow) -> None:
    remote, local = _AnomalyDetector(), _AnomalyDetector()

    WindowedAnomalyDetector(remote, local, usage_window).evaluate([(20.0, 2.0, 0.0)], (20.0, 2.0, 0.0))

    assert (remote.calls, local.calls) == (0, 1)


def test_anomalies_use_the_service_inside_the_window(usage_window: InteractiveUsageWindow) -> None:
    remote, local = _AnomalyDetector(), _AnomalyDetector()
    usage_window.record_use()

    result = WindowedAnomalyDetector(remote, local, usage_window).evaluate([(20.0, 2.0, 0.0)], (400.0, 2.0, 0.0))

    assert result == _CLASSIFICATION
    assert (remote.calls, local.calls) == (1, 0)


def test_anomalies_fall_back_to_the_local_package_if_the_service_fails(usage_window: InteractiveUsageWindow) -> None:
    remote, local = _AnomalyDetector(fails=True), _AnomalyDetector()
    usage_window.record_use()

    result = WindowedAnomalyDetector(remote, local, usage_window).evaluate([(20.0, 2.0, 0.0)], (400.0, 2.0, 0.0))

    assert result == _CLASSIFICATION
    assert (remote.calls, local.calls) == (1, 1)


def test_background_evaluations_do_not_keep_the_window_open(
    usage_window: InteractiveUsageWindow, clock: _FakeClock
) -> None:
    remote, local = _AnomalyDetector(), _AnomalyDetector()
    detector = WindowedAnomalyDetector(remote, local, usage_window)
    usage_window.record_use()

    # Una medición por minuto durante 15 minutos: las primeras van al servicio, luego la ventana se cierra sola.
    for _ in range(15):
        clock.now += 60
        detector.evaluate([(20.0, 2.0, 0.0)], (20.0, 2.0, 0.0))

    assert (remote.calls, local.calls) == (10, 5)


def test_outages_use_the_local_package_while_the_window_is_closed(usage_window: InteractiveUsageWindow) -> None:
    remote, local = _OutageDetector(), _OutageDetector()

    WindowedOutageDetector(remote, local, usage_window).detect([])

    assert (remote.calls, local.calls) == (0, 1)


def test_outages_use_the_service_inside_the_window(usage_window: InteractiveUsageWindow) -> None:
    remote, local = _OutageDetector(), _OutageDetector()
    usage_window.record_use()

    assert WindowedOutageDetector(remote, local, usage_window).detect([]) == _EPISODE
    assert (remote.calls, local.calls) == (1, 0)


def test_outages_fall_back_to_the_local_package_if_the_service_fails(usage_window: InteractiveUsageWindow) -> None:
    remote, local = _OutageDetector(fails=True), _OutageDetector()
    usage_window.record_use()

    assert WindowedOutageDetector(remote, local, usage_window).detect([]) == _EPISODE
    assert (remote.calls, local.calls) == (1, 1)
