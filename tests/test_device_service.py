"""Chequeo minimo sin DB/red: valida filtrado por owner y la sincronización de un escaneo real."""
import uuid
from datetime import datetime, timezone

from app.models.device import Device
from app.repositories.device_repository import DeviceRepository
from app.schemas.device import DeviceCreate, DeviceSyncItem, DeviceUpdate
from app.services.device_service import DeviceNotFoundError, DeviceService


class FakeDeviceRepository(DeviceRepository):
    def __init__(self) -> None:
        self.devices: dict[uuid.UUID, Device] = {}

    def list_by_owner(self, owner_id: uuid.UUID) -> list[Device]:
        return [d for d in self.devices.values() if d.owner_id == owner_id]

    def get_by_id(self, device_id: uuid.UUID, owner_id: uuid.UUID) -> Device | None:
        device = self.devices.get(device_id)
        return device if device and device.owner_id == owner_id else None

    def get_by_mac(self, owner_id: uuid.UUID, mac_address: str) -> Device | None:
        return next(
            (d for d in self.devices.values() if d.owner_id == owner_id and d.mac_address == mac_address), None
        )

    def create(
        self,
        owner_id: uuid.UUID,
        name: str,
        mac_address: str,
        ip_address: str,
        trust: str,
        last_seen: datetime | None = None,
    ) -> Device:
        seen = last_seen or datetime.now(timezone.utc)
        device = Device(
            id=uuid.uuid4(),
            owner_id=owner_id,
            name=name,
            mac_address=mac_address,
            ip_address=ip_address,
            trust=trust,
            first_seen=seen,
            last_seen=seen,
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


def test_list_devices_only_returns_those_of_the_owner() -> None:
    repository = FakeDeviceRepository()
    service = DeviceService(repository)
    owner_id = uuid.uuid4()
    other_owner_id = uuid.uuid4()
    mine = service.create_device(owner_id, DeviceCreate(name="a", mac_address="AA", ip_address="1.1.1.1"))
    service.create_device(other_owner_id, DeviceCreate(name="b", mac_address="BB", ip_address="1.1.1.2"))

    assert [d.id for d in service.list_devices(owner_id)] == [mine.id]


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


def test_sync_creates_new_devices_discovered_by_a_real_scan() -> None:
    repository = FakeDeviceRepository()
    service = DeviceService(repository)
    owner_id = uuid.uuid4()

    devices = service.sync_discovered_devices(
        owner_id, [DeviceSyncItem(mac_address="AA-BB", ip_address="192.168.1.10")]
    )

    assert len(devices) == 1
    assert devices[0].mac_address == "AA-BB"
    assert devices[0].name == ""
    assert devices[0].trust == "unknown"


def test_sync_does_not_duplicate_an_already_known_mac_and_refreshes_its_ip() -> None:
    repository = FakeDeviceRepository()
    service = DeviceService(repository)
    owner_id = uuid.uuid4()
    existing = service.create_device(
        owner_id, DeviceCreate(name="Laptop", mac_address="AA-BB", ip_address="192.168.1.10", trust="trusted")
    )

    devices = service.sync_discovered_devices(
        owner_id, [DeviceSyncItem(mac_address="AA-BB", ip_address="192.168.1.99")]
    )

    assert len(devices) == 1
    assert devices[0].id == existing.id
    assert devices[0].name == "Laptop"  # el sync no pisa el nombre puesto por el usuario
    assert devices[0].trust == "trusted"  # ni la confianza
    assert devices[0].ip_address == "192.168.1.99"


def test_sync_does_not_delete_a_device_missing_from_the_latest_scan() -> None:
    repository = FakeDeviceRepository()
    service = DeviceService(repository)
    owner_id = uuid.uuid4()
    gone = service.create_device(owner_id, DeviceCreate(name="Old phone", mac_address="CC-DD", ip_address="1.1.1.1"))

    devices = service.sync_discovered_devices(
        owner_id, [DeviceSyncItem(mac_address="AA-BB", ip_address="192.168.1.10")]
    )

    assert gone.id in [d.id for d in devices]  # sigue existiendo, con su last_seen viejo intacto


if __name__ == "__main__":
    test_list_devices_only_returns_those_of_the_owner()
    test_update_device_of_another_owner_raises_not_found()
    test_sync_creates_new_devices_discovered_by_a_real_scan()
    test_sync_does_not_duplicate_an_already_known_mac_and_refreshes_its_ip()
    test_sync_does_not_delete_a_device_missing_from_the_latest_scan()
    print("OK")
