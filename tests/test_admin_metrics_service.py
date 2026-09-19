"""Chequeo minimo sin DB/red: valida que las métricas de admin combinen los
dominios existentes (usuarios, hogares, alertas) sin recalcular nada."""
import uuid

from app.services.admin_metrics_service import AdminMetricsService
from app.services.network_supervision_service import NetworkSupervisionService
from tests.test_alert_service import FakeAlertRepository
from tests.test_device_service import FakeDeviceRepository
from tests.test_network_metrics_service import FakeNetworkMetricsRepository
from tests.test_user_service import FakeUserRepository


def _build_service(user_repository, alert_repository, device_repository=None, network_metrics_repository=None):
    supervision = NetworkSupervisionService(
        user_repository,
        device_repository or FakeDeviceRepository(),
        alert_repository,
        network_metrics_repository or FakeNetworkMetricsRepository(),
    )
    return AdminMetricsService(user_repository, alert_repository, supervision)


def test_platform_metrics_are_zero_without_any_data() -> None:
    service = _build_service(FakeUserRepository(), FakeAlertRepository())

    metrics = service.get_platform_metrics()

    assert metrics.total_users == 0
    assert metrics.monitored_households == 0
    assert metrics.active_alerts == 0
    assert metrics.average_security_score == 0


def test_platform_metrics_combine_users_households_alerts_and_average_score() -> None:
    user_repository = FakeUserRepository()
    owner_a = user_repository.create(uuid.uuid4(), "a@redsana.dev", "A", "standard")
    owner_b = user_repository.create(uuid.uuid4(), "b@redsana.dev", "B", "standard")
    user_repository.create(uuid.uuid4(), "admin@redsana.dev", "Admin", "admin")

    alert_repository = FakeAlertRepository()
    alert_repository.create(owner_a.id, "outage", "critical", "a", None, None)
    acked = alert_repository.create(owner_b.id, "outage", "warning", "b", None, None)
    alert_repository.acknowledge(acked.id, owner_b.id)

    service = _build_service(user_repository, alert_repository)

    metrics = service.get_platform_metrics()

    # total_users cuenta TODOS los roles (3); monitored_households solo standard (2)
    assert metrics.total_users == 3
    assert metrics.monitored_households == 2
    # una sola alerta sin reconocer en toda la plataforma (la de owner_b ya se reconoció)
    assert metrics.active_alerts == 1
    # owner_a: 50 (sin dispositivos) + 20 (1 alerta sin reconocer) + 10 (red "unknown") = 80
    # owner_b: 50 + 30 (alerta reconocida) + 10 = 90 -> promedio 85
    assert metrics.average_security_score == 85


if __name__ == "__main__":
    test_platform_metrics_are_zero_without_any_data()
    test_platform_metrics_combine_users_households_alerts_and_average_score()
    print("OK")
