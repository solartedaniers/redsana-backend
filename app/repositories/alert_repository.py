import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from app.models.alert import Alert


class AlertRepository(ABC):

    @abstractmethod
    def list_all(self, owner_id: uuid.UUID) -> list[Alert]: ...

    @abstractmethod
    def list_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Alert]]:
        """Una sola consulta para varios dueños (p. ej. supervisión de admin)."""
        ...

    @abstractmethod
    def count_unacknowledged_all(self) -> int:
        """Alertas sin reconocer de toda la plataforma, para el admin; a diferencia del resto, no filtra por dueño."""
        ...

    @abstractmethod
    def list_new_since(self, owner_id: uuid.UUID, since: datetime) -> list[Alert]: ...

    @abstractmethod
    def get_by_id(self, alert_id: uuid.UUID, owner_id: uuid.UUID) -> Alert | None: ...

    @abstractmethod
    def get_latest_unacknowledged(self, owner_id: uuid.UUID, type_: str) -> Alert | None:
        """Para no duplicar alertas automáticas: si ya hay una sin reconocer del mismo tipo, no creo otra."""
        ...

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
