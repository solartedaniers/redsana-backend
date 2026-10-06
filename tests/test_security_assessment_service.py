"""Chequeo minimo sin DB: valida el recalculo de score/recomendaciones y que
"no sé" puntúe igual que "no"."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.security_assessment import SecurityAssessment
from app.repositories.security_assessment_repository import SecurityAssessmentRepository
from app.schemas.security_assessment import SecurityAssessmentCreate
from app.services.network_security_score_service import default_network_security_score_service
from app.services.security_assessment_service import SecurityAssessmentService
from app.services.technical_evidence_resolver import has_technical_evidence

ALL_YES_ANSWERS = {
    "default-password": "yes",
    "firmware-updated": "yes",
    "guest-network": "yes",
    "remote-management-off": "yes",
}


def _service(repository: SecurityAssessmentRepository) -> SecurityAssessmentService:
    return SecurityAssessmentService(repository, default_network_security_score_service())


class FakeSecurityAssessmentRepository(SecurityAssessmentRepository):
    def __init__(self) -> None:
        self.assessments: list[SecurityAssessment] = []

    def get_latest(self, owner_id: uuid.UUID) -> SecurityAssessment | None:
        owned = [a for a in self.assessments if a.owner_id == owner_id]
        return max(owned, key=lambda a: a.submitted_at) if owned else None

    def get_latest_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityAssessment]:
        return {
            owner_id: latest
            for owner_id in owner_ids
            if (latest := self.get_latest(owner_id)) is not None
        }

    def get_latest_with_evidence(self, owner_id: uuid.UUID) -> SecurityAssessment | None:
        owned = [a for a in self.assessments if a.owner_id == owner_id and has_technical_evidence(a)]
        return max(owned, key=lambda a: a.submitted_at) if owned else None

    def get_latest_with_evidence_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityAssessment]:
        return {
            owner_id: latest
            for owner_id in owner_ids
            if (latest := self.get_latest_with_evidence(owner_id)) is not None
        }

    def create(
        self,
        owner_id: uuid.UUID,
        answers: dict[str, str],
        wifi_encryption_raw: str | None,
        router_open_ports: list[int] | None,
    ) -> SecurityAssessment:
        assessment = SecurityAssessment(
            id=uuid.uuid4(),
            owner_id=owner_id,
            answers=answers,
            wifi_encryption_raw=wifi_encryption_raw,
            router_open_ports=router_open_ports,
            submitted_at=datetime.now(timezone.utc) + timedelta(minutes=len(self.assessments)),
        )
        self.assessments.append(assessment)
        return assessment


def test_get_latest_assessment_returns_none_without_data() -> None:
    service = _service(FakeSecurityAssessmentRepository())

    assert service.get_latest_assessment(uuid.uuid4()) is None


def test_all_yes_strong_wifi_and_clean_router_scores_100_with_no_recommendations() -> None:
    service = _service(FakeSecurityAssessmentRepository())

    result = service.submit_assessment(
        uuid.uuid4(),
        SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA3", router_open_ports=[]),
    )

    assert result.security_score.score == 100
    assert result.security_score.recommendations == []


def test_no_and_unknown_both_score_zero_but_get_distinct_recommendation_copy() -> None:
    service = _service(FakeSecurityAssessmentRepository())

    no_result = service.submit_assessment(
        uuid.uuid4(),
        SecurityAssessmentCreate(answers={**ALL_YES_ANSWERS, "default-password": "no"}, wifi_encryption_raw="WPA3"),
    )
    unknown_result = service.submit_assessment(
        uuid.uuid4(),
        SecurityAssessmentCreate(
            answers={**ALL_YES_ANSWERS, "default-password": "unknown"}, wifi_encryption_raw="WPA3"
        ),
    )

    # Cuestionario 55/80 -> 69; técnico 100 -> 69 * 30% + 100 * 70% = 91.
    assert no_result.security_score.questionnaire_score == unknown_result.security_score.questionnaire_score == 69
    assert no_result.security_score.score == unknown_result.security_score.score == 91
    assert [r.id for r in no_result.security_score.recommendations] == ["change-default-password"]
    assert [r.id for r in unknown_result.security_score.recommendations] == ["check-default-password"]


def test_latest_assessment_recomputes_from_stored_answers_and_evidence() -> None:
    repository = FakeSecurityAssessmentRepository()
    service = _service(repository)
    owner_id = uuid.uuid4()

    submitted = service.submit_assessment(
        owner_id, SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA2", router_open_ports=[23])
    )
    latest = service.get_latest_assessment(owner_id)

    assert latest is not None
    assert latest.security_score == submitted.security_score
    assert [r.id for r in latest.security_score.recommendations] == ["router-port-closeTelnet"]


def test_assessment_without_technical_evidence_is_partial_questionnaire_only() -> None:
    service = _service(FakeSecurityAssessmentRepository())

    result = service.submit_assessment(uuid.uuid4(), SecurityAssessmentCreate(answers=ALL_YES_ANSWERS))

    assert result.security_score.is_partial
    assert result.security_score.technical_score is None
    assert result.security_score.score == result.security_score.questionnaire_score == 100


WEB_SUBMISSION = SecurityAssessmentCreate(answers=ALL_YES_ANSWERS)


def test_web_submission_reuses_the_last_desktop_measurement_with_its_date() -> None:
    service = _service(FakeSecurityAssessmentRepository())
    owner_id = uuid.uuid4()
    desktop = service.submit_assessment(
        owner_id, SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA2", router_open_ports=[23])
    )

    web = service.submit_assessment(owner_id, WEB_SUBMISSION)

    assert not web.security_score.is_partial
    assert web.security_score == desktop.security_score  # mismas respuestas + misma evidencia real
    assert web.technical_evidence_reused
    assert web.technical_measured_at == desktop.submitted_at


def test_web_submission_without_any_previous_measurement_stays_partial() -> None:
    service = _service(FakeSecurityAssessmentRepository())

    web = service.submit_assessment(uuid.uuid4(), WEB_SUBMISSION)

    assert web.security_score.is_partial
    assert web.technical_measured_at is None
    assert not web.technical_evidence_reused


def test_a_new_desktop_measurement_always_prevails_over_older_evidence() -> None:
    service = _service(FakeSecurityAssessmentRepository())
    owner_id = uuid.uuid4()
    service.submit_assessment(
        owner_id, SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA2", router_open_ports=[23])
    )
    service.submit_assessment(owner_id, WEB_SUBMISSION)

    fresh = service.submit_assessment(
        owner_id, SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA3", router_open_ports=[])
    )
    later_web = service.submit_assessment(owner_id, WEB_SUBMISSION)

    assert fresh.security_score.score == 100 and not fresh.technical_evidence_reused
    # La siguiente evaluación web ya reutiliza la medición nueva, no la vieja con Telnet.
    assert later_web.technical_measured_at == fresh.submitted_at
    assert later_web.security_score.score == 100


def test_evidence_is_never_borrowed_from_another_user() -> None:
    service = _service(FakeSecurityAssessmentRepository())
    service.submit_assessment(
        uuid.uuid4(), SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA3", router_open_ports=[])
    )

    assert service.submit_assessment(uuid.uuid4(), WEB_SUBMISSION).security_score.is_partial


if __name__ == "__main__":
    test_get_latest_assessment_returns_none_without_data()
    test_all_yes_strong_wifi_and_clean_router_scores_100_with_no_recommendations()
    test_no_and_unknown_both_score_zero_but_get_distinct_recommendation_copy()
    test_latest_assessment_recomputes_from_stored_answers_and_evidence()
    test_assessment_without_technical_evidence_is_partial_questionnaire_only()
    test_web_submission_reuses_the_last_desktop_measurement_with_its_date()
    test_web_submission_without_any_previous_measurement_stays_partial()
    test_a_new_desktop_measurement_always_prevails_over_older_evidence()
    test_evidence_is_never_borrowed_from_another_user()
    print("OK")
