import uuid
from dataclasses import dataclass
from datetime import datetime

from app.domain.security_analyzers import TechnicalEvidence
from app.models.security_assessment import SecurityAssessment
from app.repositories.security_assessment_repository import SecurityAssessmentRepository
from app.schemas.security_assessment import SecurityAssessmentCreate
from app.services.network_security_score_service import NetworkSecurityScore, NetworkSecurityScoreService
from app.services.technical_evidence_resolver import TechnicalEvidenceResolver


@dataclass(frozen=True)
class SecurityAssessmentResult:
    id: uuid.UUID
    answers: dict[str, str]
    technical_evidence: TechnicalEvidence
    security_score: NetworkSecurityScore
    submitted_at: datetime
    technical_measured_at: datetime | None
    technical_evidence_reused: bool


class SecurityAssessmentService:
    """Persiste evaluaciones y delega el cálculo del puntaje en
    NetworkSecurityScoreService (nunca se guarda el puntaje ya calculado)."""

    def __init__(self, repository: SecurityAssessmentRepository, score_service: NetworkSecurityScoreService) -> None:
        self._repository = repository
        self._score_service = score_service
        self._evidence_resolver = TechnicalEvidenceResolver(repository)

    def get_latest_assessment(self, owner_id: uuid.UUID) -> SecurityAssessmentResult | None:
        assessment = self._repository.get_latest(owner_id)
        return self._to_result(assessment) if assessment is not None else None

    def submit_assessment(self, owner_id: uuid.UUID, payload: SecurityAssessmentCreate) -> SecurityAssessmentResult:
        assessment = self._repository.create(
            owner_id, payload.answers, payload.wifi_encryption_raw, payload.router_open_ports
        )
        return self._to_result(assessment)

    def _to_result(self, assessment: SecurityAssessment) -> SecurityAssessmentResult:
        # Se recalcula siempre desde lo crudo guardado (respuestas + evidencia),
        # para que un cambio de pesos aplique también a evaluaciones pasadas.
        resolved = self._evidence_resolver.resolve(assessment)
        return SecurityAssessmentResult(
            id=assessment.id,
            answers=assessment.answers,
            technical_evidence=resolved.evidence,
            security_score=self._score_service.evaluate(assessment.answers, resolved.evidence),
            submitted_at=assessment.submitted_at,
            technical_measured_at=resolved.measured_at,
            technical_evidence_reused=resolved.is_reused,
        )
