import uuid
from abc import ABC, abstractmethod

from app.models.security_assessment import SecurityAssessment


class SecurityAssessmentRepository(ABC):
    """Contrato de acceso a datos para evaluaciones de seguridad del router."""

    @abstractmethod
    def get_latest(self, owner_id: uuid.UUID) -> SecurityAssessment | None: ...

    @abstractmethod
    def create(
        self, owner_id: uuid.UUID, answers: dict[str, str], wifi_encryption_raw: str | None
    ) -> SecurityAssessment: ...
