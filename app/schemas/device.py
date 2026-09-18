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


class DeviceCreate(BaseModel):
    name: str
    mac_address: str
    ip_address: str
    trust: DeviceTrust = "unknown"


class DeviceUpdate(BaseModel):
    name: str | None = None
    ip_address: str | None = None
    trust: DeviceTrust | None = None
