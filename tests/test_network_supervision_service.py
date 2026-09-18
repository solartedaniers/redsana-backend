"""Chequeo minimo sin DB/red: valida el filtrado a hogares standard y el proxy de security score."""
import uuid

from app.services.network_supervision_service import NetworkSupervisionService
from tests.test_alert_service import FakeAlertRepository
from tests.test_device_service import FakeDeviceRepository
from tests.test_network_metrics_service import FakeNetworkMetricsRepository
from tests.test_user_service import FakeUserRepository


def test_list_households_excludes_admin_users() -> None:
    user_repository = FakeUserRepository()
    standard_user = user_repository.create(uuid.uuid4(), "user@redsana.dev", "Usuario", "standard")
    user_repository.create(uuid.uuid4(), "admin@redsana.dev", "Admin", "admin")
    service = NetworkSupervisionService(
        user_repository, FakeDeviceRepository(), FakeAlertRepository(), FakeNetworkMetricsRepository()
    )

    households = service.list_households()

    assert [h.id for h in households] == [standard_user.id]
    assert households[0].label == "user@redsana.dev"


def test_security_score_combines_device_trust_alerts_and_network_status() -> None:
    user_repository = FakeUserRepository()
    owner = user_repository.create(uuid.uuid4(), "owner@redsana.dev", "Owner", "standard")

    device_repository = FakeDeviceRepository()
    device_repository.create(owner.id, "trusted-1", "AA:AA", "1.1.1.1", "trusted")
    device_repository.create(owner.id, "blocked-1", "BB:BB", "1.1.1.2", "blocked")

    alert_repository = FakeAlertRepository()
    alert_repository.create(owner.id, "outage", "critical", "a", None, None)

    network_metrics_repository = FakeNetworkMetricsRepository()
    network_metrics_repository.create(
        owner.id, latency_ms=20, jitter_ms=1, packet_loss_percent=0, status="good", recorded_at=None
    )

    service = NetworkSupervisionService(user_repository, device_repository, alert_repository, network_metrics_repository)

    household = service.list_households()[0]

    # 50% dispositivos de confianza (25/50) + 1 alerta sin reconocer (20/30) + red "good" (20/20)
    assert household.security_score == 65
    assert household.status == "good"


def test_security_score_defaults_when_no_devices_alerts_or_metrics_exist() -> None:
    user_repository = FakeUserRepository()
    owner = user_repository.create(uuid.uuid4(), "solo@redsana.dev", "Solo", "standard")
    service = NetworkSupervisionService(
        user_repository, FakeDeviceRepository(), FakeAlertRepository(), FakeNetworkMetricsRepository()
    )

    household = service.list_households()[0]

    # Sin evidencia negativa: dispositivos y alertas puntuan completo, red "unknown" puntua mitad
    assert household.security_score == 90
    assert household.status == "unknown"
    assert household.last_activity == owner.created_at


if __name__ == "__main__":
    test_list_households_excludes_admin_users()
    test_security_score_combines_device_trust_alerts_and_network_status()
    test_security_score_defaults_when_no_devices_alerts_or_metrics_exist()
    print("OK")
