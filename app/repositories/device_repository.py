import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.models.device import Device


class DeviceRepository(ABC):

    @abstractmethod
    def list_by_owner(self, owner_id: uuid.UUID) -> list[Device]: ...

    @abstractmethod
    def list_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Device]]:
        """Una sola consulta para varios dueños en vez de repetir list_by_owner N veces."""
        ...

    @abstractmethod
    def get_by_id(self, device_id: uuid.UUID, owner_id: uuid.UUID) -> Device | None: ...

    @abstractmethod
    def create(
        self,
        owner_id: uuid.UUID,
        name: str,
        mac_address: str,
        ip_address: str,
        trust: str,
        last_seen: datetime | None = None,
        network_role: str | None = None,
    ) -> Device: ...

    @abstractmethod
    def update(self, device_id: uuid.UUID, owner_id: uuid.UUID, updates: dict[str, Any]) -> Device | None: ...

    @abstractmethod
    def save_scan(
        self, owner_id: uuid.UUID, new_devices: list[dict[str, Any]], updates: dict[uuid.UUID, dict[str, Any]]
    ) -> list[Device]:
        """Guarda un escaneo completo en UNA transacción: un lote a medias se leía como si fuera la red entera."""
        ...
