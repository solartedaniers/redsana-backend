import uuid
from datetime import datetime, timezone

from app.models.device import Device
from app.repositories.device_repository import DeviceRepository
from app.schemas.device import DeviceCreate, DeviceSyncItem, DeviceUpdate

# Un dispositivo recién descubierto no tiene nombre real (el escaneo ARP no lo
# provee); se deja vacío en vez de inventar uno, y el frontend decide cómo mostrarlo.
DISCOVERED_DEVICE_NAME = ""


class DeviceNotFoundError(Exception):
    pass


class DeviceService:
    def __init__(self, repository: DeviceRepository) -> None:
        self._repository = repository

    def list_devices(self, owner_id: uuid.UUID) -> list[Device]:
        return self._repository.list_by_owner(owner_id)

    def create_device(self, owner_id: uuid.UUID, payload: DeviceCreate) -> Device:
        return self._repository.create(
            owner_id=owner_id,
            name=payload.name,
            mac_address=payload.mac_address,
            ip_address=payload.ip_address,
            trust=payload.trust,
        )

    def update_device(self, device_id: uuid.UUID, owner_id: uuid.UUID, payload: DeviceUpdate) -> Device:
        updates = payload.model_dump(exclude_unset=True)
        device = self._repository.update(device_id, owner_id, updates) if updates else self._repository.get_by_id(
            device_id, owner_id
        )
        if device is None:
            raise DeviceNotFoundError(f"Device '{device_id}' does not exist")
        return device

    def sync_discovered_devices(self, owner_id: uuid.UUID, discovered: list[DeviceSyncItem]) -> list[Device]:
        """Alta/actualización a partir de un escaneo real (Tauri + ARP): crea los
        dispositivos nuevos con confianza "unknown" y actualiza ip/last_seen de los
        ya existentes (identificados por MAC). No borra nada: un dispositivo que
        deja de aparecer en el escaneo simplemente deja de estar "online" (ver
        app.domain.device_presence), pero conserva su historial."""
        sync_time = datetime.now(timezone.utc)
        for item in discovered:
            existing = self._repository.get_by_mac(owner_id, item.mac_address)
            if existing is None:
                self._repository.create(
                    owner_id=owner_id,
                    name=DISCOVERED_DEVICE_NAME,
                    mac_address=item.mac_address,
                    ip_address=item.ip_address,
                    trust="unknown",
                    last_seen=sync_time,
                )
            else:
                self._repository.update(
                    existing.id, owner_id, {"ip_address": item.ip_address, "last_seen": sync_time}
                )
        return self._repository.list_by_owner(owner_id)
