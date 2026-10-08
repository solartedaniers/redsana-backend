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

    def list_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Device]]:
        if not owner_ids:
            return {}
        stmt = select(Device).where(Device.owner_id.in_(owner_ids))
        result: dict[uuid.UUID, list[Device]] = {owner_id: [] for owner_id in owner_ids}
        for device in self._db.scalars(stmt).all():
            result[device.owner_id].append(device)
        return result

    def get_by_id(self, device_id: uuid.UUID, owner_id: uuid.UUID) -> Device | None:
        stmt = select(Device).where(Device.id == device_id, Device.owner_id == owner_id)
        return self._db.scalars(stmt).first()

    def create(
        self,
        owner_id: uuid.UUID,
        name: str,
        mac_address: str,
        ip_address: str,
        trust: str,
        last_seen: datetime | None = None,
        network_role: str | None = None,
    ) -> Device:
        device = Device(
            owner_id=owner_id,
            name=name,
            mac_address=mac_address,
            ip_address=ip_address,
            trust=trust,
            network_role=network_role,
        )
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

    def save_scan(
        self, owner_id: uuid.UUID, new_devices: list[dict[str, Any]], updates: dict[uuid.UUID, dict[str, Any]]
    ) -> list[Device]:
        # Los ids de updates vienen de list_by_owner del mismo owner (ver
        # DeviceService); se vuelven a filtrar por owner aqui por seguridad.
        for device in self.list_by_owner(owner_id):
            for field, value in updates.get(device.id, {}).items():
                setattr(device, field, value)
        self._db.add_all(Device(owner_id=owner_id, **fields) for fields in new_devices)
        self._db.commit()
        return self.list_by_owner(owner_id)

    def update(self, device_id: uuid.UUID, owner_id: uuid.UUID, updates: dict[str, Any]) -> Device | None:
        device = self.get_by_id(device_id, owner_id)
        if device is None:
            return None

        for field, value in updates.items():
            setattr(device, field, value)

        self._db.commit()
        self._db.refresh(device)
        return device
