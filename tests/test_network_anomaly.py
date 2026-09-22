"""Chequeo minimo sin DB: valida el detector (IsolationForest real, sin mocks,
datos sinteticos) y la clasificacion de severidad/mensaje por separado."""
from app.domain.network_anomaly import NetworkAnomalyDetector, NetworkMetricVector, classify_deviation

# Red domestica "normal": latencia ~20ms, jitter ~2ms, perdida ~0%, con algo de
# ruido para que StandardScaler tenga una desviacion real que no sea cero.
_NORMAL_HISTORY: list[NetworkMetricVector] = [
    (20.0 + (i % 5) * 0.4, 2.0 + (i % 3) * 0.1, 0.0 + (i % 2) * 0.05) for i in range(60)
]


def test_is_anomalous_returns_false_for_a_sample_within_the_normal_range() -> None:
    detector = NetworkAnomalyDetector()

    assert detector.is_anomalous(_NORMAL_HISTORY, (21.0, 2.1, 0.05)) is False


def test_is_anomalous_returns_true_for_a_sample_far_outside_the_normal_range() -> None:
    detector = NetworkAnomalyDetector()

    assert detector.is_anomalous(_NORMAL_HISTORY, (400.0, 2.0, 0.0)) is True


def test_classify_deviation_picks_the_metric_with_the_largest_z_score() -> None:
    result = classify_deviation(_NORMAL_HISTORY, (400.0, 2.0, 0.0))

    assert result.deviating_metric == "latency"
    assert result.message_key == "alertsCenter.messages.latencyDegraded"


def test_classify_deviation_is_critical_for_a_very_large_deviation() -> None:
    result = classify_deviation(_NORMAL_HISTORY, (400.0, 2.0, 0.0))

    assert result.severity == "critical"


def test_classify_deviation_is_warning_for_a_mild_deviation() -> None:
    # z aprox 2 en latencia (desviacion tipica ~0.35 en _NORMAL_HISTORY): notorio
    # pero lejos del umbral critico de 3 desviaciones.
    result = classify_deviation(_NORMAL_HISTORY, (20.7, 2.0, 0.0))

    assert result.severity == "warning"


def test_classify_deviation_identifies_packet_loss_deviation() -> None:
    result = classify_deviation(_NORMAL_HISTORY, (20.0, 2.0, 15.0))

    assert result.deviating_metric == "packet_loss"
    assert result.message_key == "alertsCenter.messages.packetsBeingLost"


if __name__ == "__main__":
    test_is_anomalous_returns_false_for_a_sample_within_the_normal_range()
    test_is_anomalous_returns_true_for_a_sample_far_outside_the_normal_range()
    test_classify_deviation_picks_the_metric_with_the_largest_z_score()
    test_classify_deviation_is_critical_for_a_very_large_deviation()
    test_classify_deviation_is_warning_for_a_mild_deviation()
    test_classify_deviation_identifies_packet_loss_deviation()
    print("OK")
