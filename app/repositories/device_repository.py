import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.models.device import Device


class DeviceRepository(ABC):
    """Contrato de acceso a datos para dispositivos, independiente de la implementacion concreta."""

    @abstractmethod
    def list_by_owner(self, owner_id: uuid.UUID) -> list[Device]: ...

    @abstractmethod
    def get_by_id(self, device_id: uuid.UUID, owner_id: uuid.UUID) -> Device | None: ...

    @abstractmethod
    def get_by_mac(self, owner_id: uuid.UUID, mac_address: str) -> Device | None: ...

    @abstractmethod
    def create(
        self,
        owner_id: uuid.UUID,
        name: str,
        mac_address: str,
        ip_address: str,
        trust: str,
        last_seen: datetime | None = None,
    ) -> Device: ...

    @abstractmethod
    def update(self, device_id: uuid.UUID, owner_id: uuid.UUID, updates: dict[str, Any]) -> Device | None: ...
