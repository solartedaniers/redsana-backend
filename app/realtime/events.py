import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EVENT_VERSION = 1

MEASUREMENT_CREATED = "measurement.created"
ALERT_CREATED = "alert.created"
DEVICES_UPDATED = "devices.updated"
EventType = Literal["measurement.created", "alert.created", "devices.updated"]


class RealtimeEvent(BaseModel):
    """Lo que viaja por el bus y llega a los sockets: {"v", "type", "owner_id", "data", "at"}."""

    model_config = ConfigDict(frozen=True)

    v: Literal[1] = EVENT_VERSION
    type: EventType
    owner_id: uuid.UUID
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime

    @classmethod
    def now(cls, type_: EventType, owner_id: uuid.UUID, data: BaseModel | None = None) -> "RealtimeEvent":
        payload = data.model_dump(mode="json") if data is not None else {}
        return cls(type=type_, owner_id=owner_id, data=payload, at=datetime.now(UTC))
