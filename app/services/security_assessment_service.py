import uuid
from dataclasses import dataclass
from datetime import datetime

from app.domain.security_assessment import SecurityRecommendation, compute_security_assessment
from app.repositories.security_assessment_repository import SecurityAssessmentRepository
from app.schemas.security_assessment import SecurityAssessmentCreate


@dataclass(frozen=True)
class SecurityAssessmentResult:
    score: int
    recommendations: list[SecurityRecommendation]
    submitted_at: datetime


class SecurityAssessmentService:
    def __init__(self, repository: SecurityAssessmentRepository) -> None:
        self._repository = repository

    def get_latest_assessment(self, owner_id: uuid.UUID) -> SecurityAssessmentResult | None:
        assessment = self._repository.get_latest(owner_id)
        if assessment is None:
            return None
        return self._to_result(assessment.answers, assessment.wifi_encryption_raw, assessment.submitted_at)

    def submit_assessment(self, owner_id: uuid.UUID, payload: SecurityAssessmentCreate) -> SecurityAssessmentResult:
        assessment = self._repository.create(owner_id, payload.answers, payload.wifi_encryption_raw)
        return self._to_result(assessment.answers, assessment.wifi_encryption_raw, assessment.submitted_at)

    @staticmethod
    def _to_result(
        answers: dict[str, str], wifi_encryption_raw: str | None, submitted_at: datetime
    ) -> SecurityAssessmentResult:
        # Score y recomendaciones se recalculan siempre desde las respuestas
        # crudas (nunca se guardan ya calculados), para que un cambio futuro
        # en los pesos/copys aplique también a evaluaciones pasadas.
        score, recommendations = compute_security_assessment(answers, wifi_encryption_raw)
        return SecurityAssessmentResult(score=score, recommendations=recommendations, submitted_at=submitted_at)
