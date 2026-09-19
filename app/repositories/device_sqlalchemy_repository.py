import uuid
from datetime import datetime
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

    def get_by_mac(self, owner_id: uuid.UUID, mac_address: str) -> Device | None:
        stmt = select(Device).where(Device.owner_id == owner_id, Device.mac_address == mac_address)
        return self._db.scalars(stmt).first()

    def create(
        self,
        owner_id: uuid.UUID,
        name: str,
        mac_address: str,
        ip_address: str,
        trust: str,
        last_seen: datetime | None = None,
    ) -> Device:
        device = Device(owner_id=owner_id, name=name, mac_address=mac_address, ip_address=ip_address, trust=trust)
        if last_seen is not None:
            # Un sync trae su propio timestamp (compartido por toda la tanda) en vez
            # de dejar que cada INSERT tome su propio server_default=func.now(),
            # para que "is_device_online" compare tiempos consistentes entre sí.
            device.first_seen = last_seen
            device.last_seen = last_seen
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
