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
    """Payload para registrar un snapshot real. owner_id es opcional: si se omite,
    el snapshot queda a nombre del usuario autenticado; solo un admin puede pasar
    el owner_id de otro usuario (mismo override que /latest y /history)."""

    owner_id: uuid.UUID | None = None
    latency_ms: float
    jitter_ms: float
    packet_loss_percent: float
    recorded_at: datetime | None = None
