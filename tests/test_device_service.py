"""Chequeo minimo sin DB/red: valida filtrado por owner y el escaneo de no confiables."""
import uuid

from app.models.device import Device
from app.repositories.device_repository import DeviceRepository
from app.schemas.device import DeviceCreate, DeviceUpdate
from app.services.device_service import DeviceNotFoundError, DeviceService


class FakeDeviceRepository(DeviceRepository):
    def __init__(self) -> None:
        self.devices: dict[uuid.UUID, Device] = {}

    def list_by_owner(self, owner_id: uuid.UUID) -> list[Device]:
        return [d for d in self.devices.values() if d.owner_id == owner_id]

    def get_by_id(self, device_id: uuid.UUID, owner_id: uuid.UUID) -> Device | None:
        device = self.devices.get(device_id)
        return device if device and device.owner_id == owner_id else None

    def create(self, owner_id: uuid.UUID, name: str, mac_address: str, ip_address: str, trust: str) -> Device:
        device = Device(
            id=uuid.uuid4(), owner_id=owner_id, name=name, mac_address=mac_address, ip_address=ip_address, trust=trust
        )
        self.devices[device.id] = device
        return device

    def update(self, device_id: uuid.UUID, owner_id: uuid.UUID, updates: dict) -> Device | None:
        device = self.get_by_id(device_id, owner_id)
        if device is None:
            return None
        for field, value in updates.items():
            setattr(device, field, value)
        return device


def test_scan_returns_only_untrusted_devices_of_the_owner() -> None:
    repository = FakeDeviceRepository()
    service = DeviceService(repository)
    owner_id = uuid.uuid4()
    other_owner_id = uuid.uuid4()
    service.create_device(owner_id, DeviceCreate(name="a", mac_address="AA", ip_address="1.1.1.1", trust="trusted"))
    unknown = service.create_device(
        owner_id, DeviceCreate(name="b", mac_address="BB", ip_address="1.1.1.2", trust="unknown")
    )
    service.create_device(
        other_owner_id, DeviceCreate(name="c", mac_address="CC", ip_address="1.1.1.3", trust="blocked")
    )

    findings = service.scan_for_untrusted_devices(owner_id)

    assert [d.id for d in findings] == [unknown.id]


def test_update_device_of_another_owner_raises_not_found() -> None:
    repository = FakeDeviceRepository()
    service = DeviceService(repository)
    device = service.create_device(
        uuid.uuid4(), DeviceCreate(name="a", mac_address="AA", ip_address="1.1.1.1")
    )

    try:
        service.update_device(device.id, uuid.uuid4(), DeviceUpdate(trust="blocked"))
        raise AssertionError("expected DeviceNotFoundError")
    except DeviceNotFoundError:
        pass


if __name__ == "__main__":
    test_scan_returns_only_untrusted_devices_of_the_owner()
    test_update_device_of_another_owner_raises_not_found()
    print("OK")
