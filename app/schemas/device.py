import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

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
    """Un dispositivo tal como lo encontró el escaneo real (Tauri/ARP); sin
    nombre, porque ese medio no lo provee."""

    mac_address: str
    ip_address: str


class DeviceSyncRequest(BaseModel):
    devices: list[DeviceSyncItem]
