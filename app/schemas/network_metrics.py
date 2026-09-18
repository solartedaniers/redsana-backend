import uuid
from datetime import datetime

from pydantic import BaseModel

from app.domain.network_status import NetworkStatus


class NetworkMetricSnapshotRead(BaseModel):
    status: NetworkStatus
    latency_ms: float
    jitter_ms: float
    packet_loss_percent: float
    updated_at: datetime


class NetworkMetricSampleRead(BaseModel):
    timestamp: datetime
    latency_ms: float


class NetworkMetricSnapshotCreate(BaseModel):
    """Payload del endpoint admin para insertar un snapshot de prueba manualmente."""

    owner_id: uuid.UUID
    latency_ms: float
    jitter_ms: float
    packet_loss_percent: float
    recorded_at: datetime | None = None
