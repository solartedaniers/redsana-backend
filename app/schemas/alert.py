import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.models.alert import Alert

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

    @classmethod
    def from_alert(cls, alert: "Alert") -> "AlertRead":
        """La misma forma en la API REST y en el evento alert.created."""
        return cls(
            id=alert.id,
            type=alert.type,
            severity=alert.severity,
            message_key=alert.message_key,
            message_params=alert.message_params,
            timestamp=alert.created_at,
            acknowledged=alert.acknowledged,
        )


class AlertCreate(BaseModel):
    owner_id: uuid.UUID
    type: AlertType
    severity: AlertSeverity
    message_key: str
    message_params: dict[str, str | float] | None = None
    created_at: datetime | None = None
