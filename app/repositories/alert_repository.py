import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from app.models.alert import Alert


class AlertRepository(ABC):
    """Contrato de acceso a datos para alertas, independiente de la implementacion concreta."""

    @abstractmethod
    def list_all(self, owner_id: uuid.UUID) -> list[Alert]: ...

    @abstractmethod
    def list_new_since(self, owner_id: uuid.UUID, since: datetime) -> list[Alert]: ...

    @abstractmethod
    def get_by_id(self, alert_id: uuid.UUID, owner_id: uuid.UUID) -> Alert | None: ...

    @abstractmethod
    def acknowledge(self, alert_id: uuid.UUID, owner_id: uuid.UUID) -> Alert | None: ...

    @abstractmethod
    def create(
        self,
        owner_id: uuid.UUID,
        type_: str,
        severity: str,
        message_key: str,
        message_params: dict | None,
        created_at: datetime | None,
    ) -> Alert: ...
