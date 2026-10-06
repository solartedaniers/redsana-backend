import uuid
from dataclasses import dataclass
from datetime import datetime

from app.domain.security_analyzers import TechnicalEvidence
from app.models.security_assessment import SecurityAssessment
from app.repositories.security_assessment_repository import SecurityAssessmentRepository


@dataclass(frozen=True)
class ResolvedTechnicalEvidence:
    evidence: TechnicalEvidence
    # Cuándo se midió de verdad esa evidencia; None si el usuario nunca la midió.
    measured_at: datetime | None
    # True si viene de una evaluación anterior (p. ej. la actual se envió desde la web).
    is_reused: bool


_NO_EVIDENCE = TechnicalEvidence(wifi_encryption_raw=None, router_open_ports=None)


def has_technical_evidence(assessment: SecurityAssessment) -> bool:
    return assessment.wifi_encryption_raw is not None or assessment.router_open_ports is not None


def _own_evidence(assessment: SecurityAssessment) -> TechnicalEvidence:
    return TechnicalEvidence(
        wifi_encryption_raw=assessment.wifi_encryption_raw, router_open_ports=assessment.router_open_ports
    )


class TechnicalEvidenceResolver:
    """Decide qué evidencia técnica usa una evaluación: la suya si la midió
    (escritorio), o la última realmente medida por ese mismo usuario si no (web).
    Nunca inventa evidencia: si no hubo ninguna medición, devuelve vacío."""

    def __init__(self, repository: SecurityAssessmentRepository) -> None:
        self._repository = repository

    def resolve(self, assessment: SecurityAssessment) -> ResolvedTechnicalEvidence:
        if has_technical_evidence(assessment):
            return ResolvedTechnicalEvidence(_own_evidence(assessment), assessment.submitted_at, is_reused=False)
        return self._reuse(self._repository.get_latest_with_evidence(assessment.owner_id))

    def resolve_latest_by_owners(
        self, latest_by_owner: dict[uuid.UUID, SecurityAssessment]
    ) -> dict[uuid.UUID, ResolvedTechnicalEvidence]:
        """Versión en bloque para la supervisión de admin: una sola consulta para
        todos los hogares cuya última evaluación no trae evidencia propia."""
        missing = [owner_id for owner_id, assessment in latest_by_owner.items() if not has_technical_evidence(assessment)]
        previous_by_owner = self._repository.get_latest_with_evidence_by_owners(missing)
        return {
            owner_id: (
                ResolvedTechnicalEvidence(_own_evidence(assessment), assessment.submitted_at, is_reused=False)
                if has_technical_evidence(assessment)
                else self._reuse(previous_by_owner.get(owner_id))
            )
            for owner_id, assessment in latest_by_owner.items()
        }

    @staticmethod
    def _reuse(previous: SecurityAssessment | None) -> ResolvedTechnicalEvidence:
        if previous is None:
            return ResolvedTechnicalEvidence(_NO_EVIDENCE, measured_at=None, is_reused=False)
        return ResolvedTechnicalEvidence(_own_evidence(previous), previous.submitted_at, is_reused=True)
