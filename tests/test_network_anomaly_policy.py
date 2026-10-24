"""Sin base: cada métrica que señala el detector de redsana_ai tiene su texto del Centro de alertas."""

from app.domain.network_anomaly_policy import ANOMALY_MESSAGE_KEYS


def test_each_deviating_metric_maps_to_its_alert_message() -> None:
    assert ANOMALY_MESSAGE_KEYS == {
        "latency": "user.alertsCenter.messages.latencyDegraded",
        "jitter": "user.alertsCenter.messages.connectionUnstable",
        "packet_loss": "user.alertsCenter.messages.packetsBeingLost",
    }
