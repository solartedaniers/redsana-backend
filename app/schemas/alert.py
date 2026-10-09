import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AlertType = Literal["outage", "prediction", "untrusted_device"]
AlertSeverity = Literal["info", "warning", "critical"]


class AlertRead(BaseModel):
    id: uuid.UUID
    type: AlertType
    severity: AlertSeverity
    message_key: str
    message_params: dict[str, str | float] | None
    timestamp: datetime
    acknowledged: bool


class AlertCreate(BaseModel):

    owner_id: uuid.UUID
    type: AlertType
    severity: AlertSeverity
    message_key: str
    message_params: dict[str, str | float] | None = None
    created_at: datetime | None = None
