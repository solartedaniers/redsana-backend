import uuid

from app.models.device import Device
from app.repositories.device_repository import DeviceRepository
from app.schemas.device import DeviceCreate, DeviceUpdate


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

    def scan_for_untrusted_devices(self, owner_id: uuid.UUID) -> list[Device]:
        """No hay acceso real a la red desde este backend: el "escaneo" reporta
        los dispositivos ya registrados que no son de confianza."""
        return [device for device in self._repository.list_by_owner(owner_id) if device.trust != "trusted"]
