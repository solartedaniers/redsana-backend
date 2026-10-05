import uuid
from abc import ABC, abstractmethod

from app.models.security_assessment import SecurityAssessment


class SecurityAssessmentRepository(ABC):
    """Contrato de acceso a datos para evaluaciones de seguridad del router."""

    @abstractmethod
    def get_latest(self, owner_id: uuid.UUID) -> SecurityAssessment | None: ...

    @abstractmethod
    def get_latest_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityAssessment]:
        """La evaluacion mas reciente de cada owner, en una sola consulta (ej.
        supervision de admin: solo los que ya respondieron el cuestionario)."""
        ...

    @abstractmethod
    def create(
        self,
        owner_id: uuid.UUID,
        answers: dict[str, str],
        wifi_encryption_raw: str | None,
        router_open_ports: list[int] | None,
    ) -> SecurityAssessment: ...
