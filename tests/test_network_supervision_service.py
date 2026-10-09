"""Sin base ni red: solo hogares estándar, el puntaje aproximado y que el del cuestionario tenga prioridad."""
import uuid

from app.services.network_security_score_service import default_network_security_score_service
from app.schemas.security_assessment import SecurityAssessmentCreate
from app.services.network_supervision_service import NetworkSupervisionService
from app.services.security_assessment_service import SecurityAssessmentService
from tests.test_alert_service import FakeAlertRepository
from tests.test_device_service import FakeDeviceRepository
from tests.test_network_metrics_service import FakeNetworkMetricsRepository
from tests.test_security_assessment_service import ALL_YES_ANSWERS, FakeSecurityAssessmentRepository
from tests.test_user_service import FakeUserRepository


def _build_service(
    user_repository=None, device_repository=None, alert_repository=None, metrics_repository=None, assessment_repository=None
) -> NetworkSupervisionService:
    return NetworkSupervisionService(
        user_repository or FakeUserRepository(),
        device_repository or FakeDeviceRepository(),
        alert_repository or FakeAlertRepository(),
        metrics_repository or FakeNetworkMetricsRepository(),
        assessment_repository or FakeSecurityAssessmentRepository(),
        default_network_security_score_service(),
    )


def test_list_households_excludes_admin_users() -> None:
    user_repository = FakeUserRepository()
    standard_user = user_repository.create(uuid.uuid4(), "user@redsana.dev", "Usuario", "standard")
    user_repository.create(uuid.uuid4(), "admin@redsana.dev", "Admin", "admin")
    service = _build_service(user_repository=user_repository)

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
        owner.id, latency_ms=20, jitter_ms=1, packet_loss_percent=0, status="good", source="native", recorded_at=None
    )

    service = _build_service(user_repository, device_repository, alert_repository, network_metrics_repository)

    household = service.list_households()[0]

    # 50 % de dispositivos de confianza (25/50) + 1 alerta sin reconocer (20/30) + red "good" (20/20)
    assert household.security_score == 65
    assert household.security_score_source == "estimated"  # sin cuestionario respondido
    assert household.status == "good"


def test_security_score_defaults_when_no_devices_alerts_or_metrics_exist() -> None:
    user_repository = FakeUserRepository()
    owner = user_repository.create(uuid.uuid4(), "solo@redsana.dev", "Solo", "standard")
    service = _build_service(user_repository=user_repository)

    household = service.list_households()[0]

    # Sin evidencia negativa: dispositivos y alertas puntúan completo y la red "unknown" la mitad
    assert household.security_score == 90
    assert household.security_score_source == "estimated"
    assert household.status == "unknown"
    assert household.last_activity == owner.created_at


def test_real_assessment_score_takes_priority_over_the_proxy() -> None:
    user_repository = FakeUserRepository()
    owner = user_repository.create(uuid.uuid4(), "answered@redsana.dev", "Answered", "standard")

    # Este hogar tendría un puntaje aproximado bajo...
    device_repository = FakeDeviceRepository()
    device_repository.create(owner.id, "blocked-1", "BB:BB", "1.1.1.2", "blocked")
    alert_repository = FakeAlertRepository()
    alert_repository.create(owner.id, "outage", "critical", "a", None, None)

    # ...pero SÍ respondió el cuestionario, y ese es el que debe mostrarse.
    assessment_repository = FakeSecurityAssessmentRepository()
    SecurityAssessmentService(assessment_repository, default_network_security_score_service()).submit_assessment(
        owner.id, SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA3")
    )

    service = _build_service(
        user_repository, device_repository, alert_repository, assessment_repository=assessment_repository
    )

    household = service.list_households()[0]

    assert household.security_score == 100  # el real del cuestionario, no el aproximado
    assert household.security_score_source == "real"



def test_household_score_uses_the_desktop_evidence_reused_by_a_web_submission() -> None:
    user_repository = FakeUserRepository()
    owner = user_repository.create(uuid.uuid4(), "owner@redsana.dev", "Owner", "standard")
    assessment_repository = FakeSecurityAssessmentRepository()
    assessments = SecurityAssessmentService(assessment_repository, default_network_security_score_service())
    desktop = assessments.submit_assessment(
        owner.id, SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA2", router_open_ports=[23])
    )
    assessments.submit_assessment(owner.id, SecurityAssessmentCreate(answers=ALL_YES_ANSWERS))

    household = _build_service(user_repository, assessment_repository=assessment_repository).list_households()[0]

    # El admin ve el mismo puntaje completo que el usuario, no el 100 de solo cuestionario.
    assert household.security_score == desktop.security_score.score < 100


def _household_after(submissions: list[SecurityAssessmentCreate]):
    user_repository = FakeUserRepository()
    owner = user_repository.create(uuid.uuid4(), "owner@redsana.dev", "Owner", "standard")
    assessment_repository = FakeSecurityAssessmentRepository()
    assessments = SecurityAssessmentService(assessment_repository, default_network_security_score_service())
    results = [assessments.submit_assessment(owner.id, submission) for submission in submissions]
    household = _build_service(user_repository, assessment_repository=assessment_repository).list_households()[0]
    return household, results


DESKTOP = SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA2", router_open_ports=[23])
WEB = SecurityAssessmentCreate(answers=ALL_YES_ANSWERS)


def test_web_only_household_is_marked_partial_without_date() -> None:
    household, _ = _household_after([WEB])

    assert household.security_score_is_partial
    assert household.security_technical_measured_at is None


def test_reused_desktop_evidence_is_complete_and_carries_its_date() -> None:
    household, (desktop, _) = _household_after([DESKTOP, WEB])

    assert not household.security_score_is_partial
    assert household.security_technical_measured_at == desktop.submitted_at


def test_fresh_desktop_score_has_no_label_and_no_date() -> None:
    household, _ = _household_after([DESKTOP])

    assert not household.security_score_is_partial
    assert household.security_technical_measured_at is None


def test_estimated_score_is_not_labelled_partial() -> None:
    household, _ = _household_after([])

    assert household.security_score_source == "estimated"
    assert not household.security_score_is_partial

if __name__ == "__main__":
    test_list_households_excludes_admin_users()
    test_security_score_combines_device_trust_alerts_and_network_status()
    test_security_score_defaults_when_no_devices_alerts_or_metrics_exist()
    test_real_assessment_score_takes_priority_over_the_proxy()
    print("OK")


def test_trusted_ratio_only_counts_devices_connected_now_excluding_router_and_this_pc() -> None:
    from datetime import datetime, timedelta, timezone

    user_repository = FakeUserRepository()
    owner = user_repository.create(uuid.uuid4(), "campus@redsana.dev", "Campus", "standard")
    now = datetime.now(timezone.utc)
    old_scan = now - timedelta(days=3)
    device_repository = FakeDeviceRepository()
    device_repository.create(owner.id, "", "R0:00", "10.0.0.1", "unknown", now, "gateway")
    device_repository.create(owner.id, "", "PC:00", "10.0.0.2", "unknown", now, "this_device")
    device_repository.create(owner.id, "", "PH:01", "10.0.0.3", "trusted", now, "other")
    # Historial de otra red o equipos que ya no están: no deben diluir el porcentaje.
    for index in range(50):
        device_repository.create(owner.id, "", f"OL:{index:02d}", "192.168.1.9", "unknown", old_scan, "other")

    service = _build_service(user_repository, device_repository, FakeAlertRepository(), FakeNetworkMetricsRepository())
    household = service.list_households()[0]

    # 1 de 1 conectado es de confianza (50/50) + sin alertas (30/30) + red sin medir (10/20)
    assert household.security_score == 90
