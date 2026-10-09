import uuid
from abc import ABC, abstractmethod

from app.models.security_assessment import SecurityAssessment


class SecurityAssessmentRepository(ABC):

    @abstractmethod
    def get_latest(self, owner_id: uuid.UUID) -> SecurityAssessment | None: ...

    @abstractmethod
    def get_latest_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityAssessment]:
        """La evaluación más reciente de cada dueño en una sola consulta (solo los que respondieron)."""
        ...

    @abstractmethod
    def get_latest_with_evidence(self, owner_id: uuid.UUID) -> SecurityAssessment | None:
        """La evaluación más reciente del dueño que sí trae evidencia técnica medida."""
        ...

    @abstractmethod
    def get_latest_with_evidence_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, SecurityAssessment]: ...

    @abstractmethod
    def create(
        self,
        owner_id: uuid.UUID,
        answers: dict[str, str],
        wifi_encryption_raw: str | None,
        router_open_ports: list[int] | None,
    ) -> SecurityAssessment: ...
