"""La IA recibe cuándo y desde dónde se midió la red, los umbrales reales y las pantallas reales, para no inventarlos."""

import uuid
from datetime import UTC, datetime, timedelta, timezone

from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.services.security_chat_context_service import SecurityChatContextBuilder

BOGOTA = timezone(timedelta(hours=-5))


def _snapshot(source: str, recorded_at: datetime) -> NetworkMetricSnapshot:
    return NetworkMetricSnapshot(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        latency_ms=263.1,
        jitter_ms=116.4,
        packet_loss_percent=0.0,
        status="critical",
        source=source,
        recorded_at=recorded_at,
    )


def test_snapshot_line_says_when_in_local_time_and_that_web_is_latency_to_the_server() -> None:
    recorded_at = datetime.now(timezone.utc) - timedelta(minutes=3, seconds=10)
    builder = SecurityChatContextBuilder(None, None, None, None, BOGOTA)

    line = builder._snapshot_line(_snapshot("web", recorded_at))

    assert f"Medido el {recorded_at.astimezone(BOGOTA):%Y-%m-%d %H:%M} (hora local, hace 3 min)" in line
    assert "latencia al servidor" in line


def test_snapshot_line_accepts_naive_utc_dates_from_sqlite_and_names_the_desktop() -> None:
    recorded_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None)
    builder = SecurityChatContextBuilder(None, None, None, None, timezone.utc)

    line = builder._snapshot_line(_snapshot("native", recorded_at))

    assert "hace 1 min" in line
    assert "app de escritorio" in line


def test_thresholds_and_screens_are_the_real_ones() -> None:
    builder = SecurityChatContextBuilder(None, None, None, None, timezone.utc)

    assert "alerta desde 80 ms" in builder._thresholds_line("native")
    assert "critica desde 150 ms o 5% de perdida" in builder._thresholds_line("native")
    assert "Panel principal (Latencia, Jitter, Pérdida de paquetes, Historial de latencia)" in builder._screens_line()
    assert "Dashboard" not in builder._screens_line()


def test_thresholds_line_uses_the_scale_of_the_last_measurement_source() -> None:
    builder = SecurityChatContextBuilder(None, None, None, None, UTC)

    assert "alerta desde 400 ms" in builder._thresholds_line("web")
    assert "critica desde 800 ms o 5% de perdida" in builder._thresholds_line("web")
