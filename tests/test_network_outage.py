"""Sin base: detección de cortes por el contenido de las filas (no por huecos), con horas sintéticas."""
from datetime import datetime, timedelta, timezone

from app.domain.network_outage import OutageSample, detect_recovered_outage

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _samples(*entries: tuple[int, float]) -> list[OutageSample]:
    """entries: (minutos atrás, packet_loss_percent), la más reciente primero."""
    return [(NOW - timedelta(minutes=minutes_ago), loss) for minutes_ago, loss in entries]


def test_no_outage_when_everything_is_normal() -> None:
    window = _samples((0, 0.0), (1, 0.0), (2, 0.0))

    assert detect_recovered_outage(window) is None


def test_no_episode_while_still_down() -> None:
    window = _samples((0, 100.0), (1, 100.0), (2, 0.0))

    assert detect_recovered_outage(window) is None


def test_detects_a_single_sample_outage_with_one_minute_duration() -> None:
    window = _samples((0, 0.0), (1, 100.0), (2, 0.0))

    episode = detect_recovered_outage(window)

    assert episode is not None
    assert episode.duration_minutes == 1
    assert episode.severity == "warning"


def test_detects_a_multi_sample_outage_and_walks_back_to_its_start() -> None:
    window = _samples((0, 0.0), (1, 100.0), (2, 100.0), (3, 100.0), (4, 0.0))

    episode = detect_recovered_outage(window)

    assert episode is not None
    # Fallan los minutos 1, 2 y 3: la duración va desde que empezó a fallar (min 3) hasta la recuperación (min 0).
    assert episode.duration_minutes == 3
    assert episode.started_at == NOW - timedelta(minutes=3)


def test_long_outage_is_critical_severity() -> None:
    entries = [(0, 0.0)] + [(m, 100.0) for m in range(1, 16)] + [(16, 0.0)]
    window = _samples(*entries)

    episode = detect_recovered_outage(window)

    assert episode is not None
    assert episode.duration_minutes >= 15
    assert episode.severity == "critical"


def test_does_not_claim_a_continuous_outage_across_a_large_gap() -> None:
    # Última mala hace 3 horas y recuperación ahora: la app seguramente estuvo cerrada, no hay corte continuo.
    window = _samples((0, 0.0), (180, 100.0), (181, 100.0))

    assert detect_recovered_outage(window) is None


def test_stops_walking_back_at_a_gap_inside_the_streak() -> None:
    # La racha reciente está bien espaciada pero antes hay un salto de horas: la duración debe cortarse ahí.
    window = _samples((0, 0.0), (1, 100.0), (2, 100.0), (180, 100.0))

    episode = detect_recovered_outage(window)

    assert episode is not None
    assert episode.duration_minutes == 2
    assert episode.started_at == NOW - timedelta(minutes=2)


if __name__ == "__main__":
    test_no_outage_when_everything_is_normal()
    test_no_episode_while_still_down()
    test_detects_a_single_sample_outage_with_one_minute_duration()
    test_detects_a_multi_sample_outage_and_walks_back_to_its_start()
    test_long_outage_is_critical_severity()
    test_does_not_claim_a_continuous_outage_across_a_large_gap()
    test_stops_walking_back_at_a_gap_inside_the_streak()
    print("OK")
