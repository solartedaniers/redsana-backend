import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.device_role import DEFAULT_DEVICE_ROLE, DeviceRole

DeviceTrust = Literal["trusted", "unknown", "blocked"]


class DeviceRead(BaseModel):
    id: uuid.UUID
    name: str
    mac_address: str
    ip_address: str
    trust: DeviceTrust
    first_seen: datetime
    last_seen: datetime
    is_online: bool
    network_role: DeviceRole | None


class DeviceCreate(BaseModel):
    name: str
    mac_address: str
    ip_address: str
    trust: DeviceTrust = "unknown"


class DeviceUpdate(BaseModel):
    name: str | None = None
    ip_address: str | None = None
    trust: DeviceTrust | None = None


class DeviceSyncItem(BaseModel):
    """Un dispositivo tal como lo encontró el escaneo real; sin nombre, porque ARP no lo da."""

    mac_address: str
    ip_address: str
    role: DeviceRole = DEFAULT_DEVICE_ROLE


class DeviceSyncRequest(BaseModel):
    devices: list[DeviceSyncItem]
