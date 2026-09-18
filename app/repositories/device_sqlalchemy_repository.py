import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.device import Device
from app.repositories.device_repository import DeviceRepository


class SqlAlchemyDeviceRepository(DeviceRepository):
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_by_owner(self, owner_id: uuid.UUID) -> list[Device]:
        stmt = select(Device).where(Device.owner_id == owner_id)
        return list(self._db.scalars(stmt).all())

    def get_by_id(self, device_id: uuid.UUID, owner_id: uuid.UUID) -> Device | None:
        stmt = select(Device).where(Device.id == device_id, Device.owner_id == owner_id)
        return self._db.scalars(stmt).first()

    def create(self, owner_id: uuid.UUID, name: str, mac_address: str, ip_address: str, trust: str) -> Device:
        device = Device(owner_id=owner_id, name=name, mac_address=mac_address, ip_address=ip_address, trust=trust)
        self._db.add(device)
        self._db.commit()
        self._db.refresh(device)
        return device

    def update(self, device_id: uuid.UUID, owner_id: uuid.UUID, updates: dict[str, Any]) -> Device | None:
        device = self.get_by_id(device_id, owner_id)
        if device is None:
            return None

        for field, value in updates.items():
            setattr(device, field, value)

        self._db.commit()
        self._db.refresh(device)
        return device
