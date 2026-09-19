import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.network_status import NetworkStatus

AdminUserRole = Literal["standard", "admin"]
AdminUserStatus = Literal["active", "suspended"]


class AdminHouseholdRead(BaseModel):
    id: uuid.UUID
    owner_name: str
    label: str
    status: NetworkStatus
    security_score: int
    last_activity: datetime


class AdminPlatformMetricsRead(BaseModel):
    total_users: int
    monitored_households: int
    active_alerts: int
    average_security_score: int


class AdminUserRead(BaseModel):
    id: uuid.UUID
    full_name: str | None
    email: str
    role: AdminUserRole
    status: AdminUserStatus
    created_at: datetime


class AdminUserCreate(BaseModel):
    full_name: str
    email: str
    role: AdminUserRole = "standard"


class AdminUserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    role: AdminUserRole | None = None
    status: AdminUserStatus | None = None
