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
    def list_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Device]]:
        """Una sola consulta para varios owners (ej. supervision de admin), en vez
        de list_by_owner uno por uno -- evita repetir la misma query N veces."""
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
        """Guarda un escaneo completo en UNA transaccion (todo o nada) y devuelve
        los dispositivos del owner. Con un commit por dispositivo, un escaneo de
        ~900 equipos cortado a la mitad dejaba un lote parcial que la regla de
        presencia leia como si fuera la red entera."""
        ...
