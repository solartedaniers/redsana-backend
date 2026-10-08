import uuid
from datetime import datetime, timezone

from app.models.device import Device
from app.repositories.device_repository import DeviceRepository
from app.schemas.device import DeviceCreate, DeviceSyncItem, DeviceUpdate

# Un dispositivo recién descubierto no tiene nombre real (el escaneo ARP no lo
# provee); se deja vacío en vez de inventar uno, y el frontend decide cómo mostrarlo.
DISCOVERED_DEVICE_NAME = ""
DISCOVERED_DEVICE_TRUST = "unknown"


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
        existing_by_mac = {device.mac_address: device for device in self._repository.list_by_owner(owner_id)}
        # Una MAC que responde por dos IPs en el mismo escaneo es un solo equipo:
        # se queda la ultima, en vez de intentar crearla dos veces (MAC unica por owner).
        discovered_by_mac = {item.mac_address: item for item in discovered}

        new_devices: list[dict] = []
        updates: dict[uuid.UUID, dict] = {}
        for mac_address, item in discovered_by_mac.items():
            # El papel se refresca en cada escaneo: el mismo equipo puede ser
            # "otro" en una red y el router de la siguiente.
            scanned = {"ip_address": item.ip_address, "last_seen": sync_time, "network_role": item.role}
            existing = existing_by_mac.get(mac_address)
            if existing is None:
                new_devices.append(
                    {
                        **scanned,
                        "mac_address": mac_address,
                        "name": DISCOVERED_DEVICE_NAME,
                        "trust": DISCOVERED_DEVICE_TRUST,
                        "first_seen": sync_time,
                    }
                )
            else:
                updates[existing.id] = scanned
        return self._repository.save_scan(owner_id, new_devices, updates)
