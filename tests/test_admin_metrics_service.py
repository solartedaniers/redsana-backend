"""Sin base ni red: las métricas de admin combinan los dominios existentes sin recalcular nada."""
import uuid

from app.services.network_security_score_service import default_network_security_score_service
from app.services.admin_metrics_service import AdminMetricsService
from app.services.network_supervision_service import NetworkSupervisionService
from tests.test_alert_service import FakeAlertRepository
from tests.test_device_service import FakeDeviceRepository
from tests.test_network_metrics_service import FakeNetworkMetricsRepository
from tests.test_security_assessment_service import FakeSecurityAssessmentRepository
from tests.test_user_service import FakeUserRepository
from app.schemas.security_assessment import SecurityAssessmentCreate
from app.services.security_assessment_service import SecurityAssessmentService
from tests.test_security_assessment_service import ALL_YES_ANSWERS


def _build_service(user_repository, alert_repository, device_repository=None, network_metrics_repository=None, assessment_repository=None):
    supervision = NetworkSupervisionService(
        user_repository,
        device_repository or FakeDeviceRepository(),
        alert_repository,
        network_metrics_repository or FakeNetworkMetricsRepository(),
        assessment_repository or FakeSecurityAssessmentRepository(),
        default_network_security_score_service(),
    )
    return AdminMetricsService(user_repository, alert_repository, supervision)


def test_platform_metrics_are_zero_without_any_data() -> None:
    service = _build_service(FakeUserRepository(), FakeAlertRepository())

    metrics = service.get_platform_metrics()

    assert metrics.total_users == 0
    assert metrics.monitored_households == 0
    assert metrics.active_alerts == 0
    assert metrics.average_security_score == 0
    assert metrics.real_scored_households == 0
    assert metrics.unevaluated_households == 0


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

    # total_users cuenta TODOS los roles (3); monitored_households solo los estándar (2)
    assert metrics.total_users == 3
    assert metrics.monitored_households == 2
    # una sola alerta sin reconocer en toda la plataforma (la de owner_b ya se reconoció)
    assert metrics.active_alerts == 1
    # Ninguno respondió el cuestionario: sus puntajes son estimados y ya no entran al promedio.
    assert metrics.real_scored_households == 0
    assert metrics.unevaluated_households == 2
    assert metrics.average_security_score == 0


def _answer(assessment_repository, owner_id, answers, wifi="WPA3") -> None:
    SecurityAssessmentService(assessment_repository, default_network_security_score_service()).submit_assessment(
        owner_id, SecurityAssessmentCreate(answers=answers, wifi_encryption_raw=wifi)
    )


def test_average_uses_only_real_scores() -> None:
    user_repository = FakeUserRepository()
    owner_a = user_repository.create(uuid.uuid4(), "a@redsana.dev", "A", "standard")
    owner_b = user_repository.create(uuid.uuid4(), "b@redsana.dev", "B", "standard")
    assessments = FakeSecurityAssessmentRepository()
    _answer(assessments, owner_a.id, ALL_YES_ANSWERS)
    _answer(assessments, owner_b.id, {}, wifi="WEP")

    metrics = _build_service(user_repository, FakeAlertRepository(), assessment_repository=assessments).get_platform_metrics()
    households = {h.id: h.security_score for h in _build_service(user_repository, FakeAlertRepository(), assessment_repository=assessments)._network_supervision_service.list_households()}

    assert metrics.real_scored_households == 2
    assert metrics.unevaluated_households == 0
    assert metrics.average_security_score == round((households[owner_a.id] + households[owner_b.id]) / 2)


def test_mix_of_real_and_unevaluated_averages_only_the_real_ones() -> None:
    user_repository = FakeUserRepository()
    answered = user_repository.create(uuid.uuid4(), "answered@redsana.dev", "Answered", "standard")
    user_repository.create(uuid.uuid4(), "pending@redsana.dev", "Pending", "standard")
    assessments = FakeSecurityAssessmentRepository()
    _answer(assessments, answered.id, ALL_YES_ANSWERS)

    metrics = _build_service(user_repository, FakeAlertRepository(), assessment_repository=assessments).get_platform_metrics()

    assert metrics.real_scored_households == 1
    assert metrics.unevaluated_households == 1
    # Solo cuenta el real (100); el estimado del otro hogar no lo baja ni lo sube.
    assert metrics.average_security_score == 100


def test_no_real_scores_reports_zero_real_households() -> None:
    user_repository = FakeUserRepository()
    user_repository.create(uuid.uuid4(), "pending@redsana.dev", "Pending", "standard")

    metrics = _build_service(user_repository, FakeAlertRepository()).get_platform_metrics()

    assert metrics.monitored_households == 1
    assert metrics.real_scored_households == 0
    assert metrics.unevaluated_households == 1
    assert metrics.average_security_score == 0


if __name__ == "__main__":
    test_platform_metrics_are_zero_without_any_data()
    test_platform_metrics_combine_users_households_alerts_and_average_score()
    print("OK")
