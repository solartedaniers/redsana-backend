"""Umbrales del estado de la red: los valores por defecto dan los mismos estados de siempre y se cambian por entorno."""

from collections.abc import Iterator

import pytest

from app.core.config import get_settings
from app.domain.network_status import compute_network_status


@pytest.fixture()
def fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


# Los mismos bordes que tenían las constantes fijas 80 / 150 ms y 1 / 5 %.
@pytest.mark.parametrize(
    ("latency_ms", "packet_loss_percent", "expected"),
    [
        (0, 0, "good"),
        (79.9, 0, "good"),
        (80, 0, "warning"),
        (149.9, 0, "warning"),
        (150, 0, "critical"),
        (20, 0.99, "good"),
        (20, 1, "warning"),
        (20, 4.99, "warning"),
        (20, 5, "critical"),
        (50, 3, "warning"),
        (0, 100, "critical"),
    ],
)
def test_default_thresholds_keep_todays_statuses(
    fresh_settings: None, latency_ms: float, packet_loss_percent: float, expected: str
) -> None:
    thresholds = get_settings().network_status_thresholds

    assert compute_network_status(latency_ms, packet_loss_percent, thresholds) == expected


def test_default_thresholds_are_80_150_1_5(fresh_settings: None) -> None:
    thresholds = get_settings().network_status_thresholds

    assert (
        thresholds.latency_warning_ms,
        thresholds.latency_critical_ms,
        thresholds.packet_loss_warning_percent,
        thresholds.packet_loss_critical_percent,
    ) == (80, 150, 1, 5)


def test_environment_variables_change_the_thresholds(fresh_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_STATUS_LATENCY_WARNING_MS", "100")
    monkeypatch.setenv("NETWORK_STATUS_PACKET_LOSS_CRITICAL_PERCENT", "10")
    thresholds = get_settings().network_status_thresholds

    assert thresholds.latency_warning_ms == 100
    assert compute_network_status(90, 0, thresholds) == "good"
    assert compute_network_status(20, 7, thresholds) == "warning"


def test_warning_above_critical_is_rejected(fresh_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_STATUS_LATENCY_WARNING_MS", "200")

    with pytest.raises(ValueError, match="NETWORK_STATUS_LATENCY_WARNING_MS"):
        get_settings()


@pytest.mark.parametrize(
    ("latency_ms", "packet_loss_percent", "expected"),
    [
        (170, 0, "good"),
        (290, 0, "good"),
        (399.9, 0, "good"),
        (400, 0, "warning"),
        (800, 0, "critical"),
        (200, 1, "warning"),
        (200, 5, "critical"),
    ],
)
def test_web_measurements_use_their_own_latency_scale(
    fresh_settings: None, latency_ms: float, packet_loss_percent: float, expected: str
) -> None:
    thresholds = get_settings().network_status_thresholds_for("web")

    assert compute_network_status(latency_ms, packet_loss_percent, thresholds) == expected


def test_native_measurements_keep_the_desktop_thresholds(fresh_settings: None) -> None:
    assert get_settings().network_status_thresholds_for("native") == get_settings().network_status_thresholds


def test_web_latency_thresholds_follow_the_environment(fresh_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_STATUS_WEB_LATENCY_WARNING_MS", "500")
    monkeypatch.setenv("NETWORK_STATUS_WEB_LATENCY_CRITICAL_MS", "1000")

    thresholds = get_settings().network_status_thresholds_for("web")

    assert (thresholds.latency_warning_ms, thresholds.latency_critical_ms) == (500, 1000)


def test_web_warning_above_critical_is_rejected(fresh_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_STATUS_WEB_LATENCY_WARNING_MS", "900")

    with pytest.raises(ValueError, match="NETWORK_STATUS_WEB_LATENCY_WARNING_MS"):
        get_settings()
