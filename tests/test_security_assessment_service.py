"""Chequeo minimo sin DB: valida el recalculo de score/recomendaciones y que
"no sé" puntúe igual que "no"."""
import uuid
from datetime import datetime, timezone

from app.models.security_assessment import SecurityAssessment
from app.repositories.security_assessment_repository import SecurityAssessmentRepository
from app.schemas.security_assessment import SecurityAssessmentCreate
from app.services.security_assessment_service import SecurityAssessmentService

ALL_YES_ANSWERS = {
    "default-password": "yes",
    "firmware-updated": "yes",
    "guest-network": "yes",
    "remote-management-off": "yes",
}


class FakeSecurityAssessmentRepository(SecurityAssessmentRepository):
    def __init__(self) -> None:
        self.assessments: list[SecurityAssessment] = []

    def get_latest(self, owner_id: uuid.UUID) -> SecurityAssessment | None:
        owned = [a for a in self.assessments if a.owner_id == owner_id]
        return max(owned, key=lambda a: a.submitted_at) if owned else None

    def create(self, owner_id: uuid.UUID, answers: dict[str, str], wifi_encryption_raw: str | None) -> SecurityAssessment:
        assessment = SecurityAssessment(
            owner_id=owner_id,
            answers=answers,
            wifi_encryption_raw=wifi_encryption_raw,
            submitted_at=datetime.now(timezone.utc),
        )
        self.assessments.append(assessment)
        return assessment


def test_get_latest_assessment_returns_none_without_data() -> None:
    service = SecurityAssessmentService(FakeSecurityAssessmentRepository())

    assert service.get_latest_assessment(uuid.uuid4()) is None


def test_all_yes_and_strong_wifi_scores_100_with_no_recommendations() -> None:
    service = SecurityAssessmentService(FakeSecurityAssessmentRepository())

    result = service.submit_assessment(
        uuid.uuid4(), SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw="WPA3")
    )

    assert result.score == 100
    assert result.recommendations == []


def test_no_and_unknown_both_score_zero_but_get_distinct_recommendation_copy() -> None:
    service = SecurityAssessmentService(FakeSecurityAssessmentRepository())

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

    assert no_result.score == unknown_result.score == 75
    assert [r.id for r in no_result.recommendations] == ["change-default-password"]
    assert [r.id for r in unknown_result.recommendations] == ["check-default-password"]


def test_latest_assessment_recomputes_from_stored_answers() -> None:
    repository = FakeSecurityAssessmentRepository()
    service = SecurityAssessmentService(repository)
    owner_id = uuid.uuid4()

    submitted = service.submit_assessment(
        owner_id, SecurityAssessmentCreate(answers=ALL_YES_ANSWERS, wifi_encryption_raw=None)
    )
    latest = service.get_latest_assessment(owner_id)

    assert latest is not None
    assert latest.score == submitted.score
    assert [r.id for r in latest.recommendations] == ["enable-wifi-encryption"]


if __name__ == "__main__":
    test_get_latest_assessment_returns_none_without_data()
    test_all_yes_and_strong_wifi_scores_100_with_no_recommendations()
    test_no_and_unknown_both_score_zero_but_get_distinct_recommendation_copy()
    test_latest_assessment_recomputes_from_stored_answers()
    print("OK")
