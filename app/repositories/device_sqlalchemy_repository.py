import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.domain.device_presence import (
    DEVICE_PRESENCE_TOLERANCE,
    NON_MEMBER_ROLES,
    TRUSTED_DEVICE_TRUST_VALUE,
    ConnectedMemberCounts,
)
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

    def count_connected_members_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, ConnectedMemberCounts]:
        # Mismas reglas que connected_members, pero en SQL: con miles de dispositivos por dueño traerlos todos en cada
        # /latest era la mayor parte de lo que salía de la base.
        counts = {owner_id: ConnectedMemberCounts(members=0, trusted=0) for owner_id in owner_ids}
        if not owner_ids:
            return counts
        latest_seen_stmt = (
            select(Device.owner_id, func.max(Device.last_seen))
            .where(Device.owner_id.in_(owner_ids))
            .group_by(Device.owner_id)
        )
        latest_seen = self._db.execute(latest_seen_stmt).all()
        if not latest_seen:
            return counts
        online = or_(
            *(
                and_(Device.owner_id == owner_id, Device.last_seen >= seen - DEVICE_PRESENCE_TOLERANCE)
                for owner_id, seen in latest_seen
            )
        )
        member = or_(Device.network_role.is_(None), Device.network_role.not_in(NON_MEMBER_ROLES))
        trusted = func.sum(case((Device.trust == TRUSTED_DEVICE_TRUST_VALUE, 1), else_=0))
        stmt = select(Device.owner_id, func.count(), trusted).where(online, member).group_by(Device.owner_id)
        for owner_id, members, trusted_members in self._db.execute(stmt):
            counts[owner_id] = ConnectedMemberCounts(members=members, trusted=trusted_members or 0)
        return counts

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
            # Toda la tanda comparte un timestamp para que is_device_online compare tiempos consistentes.
            device.first_seen = last_seen
            device.last_seen = last_seen
        self._db.add(device)
        self._db.commit()
        self._db.refresh(device)
        return device

    def save_scan(
        self, owner_id: uuid.UUID, new_devices: list[dict[str, Any]], updates: dict[uuid.UUID, dict[str, Any]]
    ) -> list[Device]:
        # Los ids ya vienen del mismo dueño, pero vuelvo a filtrar por dueño por seguridad.
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
