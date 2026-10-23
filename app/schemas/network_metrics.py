import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.measurement_source import DEFAULT_MEASUREMENT_SOURCE, MeasurementSource
from app.domain.network_status import NetworkStatus


class NetworkMetricSnapshotRead(BaseModel):
    status: NetworkStatus
    latency_ms: float
    jitter_ms: float
    packet_loss_percent: float
    updated_at: datetime
    # El frontend rotula la web como "latencia al servidor"; None mientras no haya mediciones.
    source: MeasurementSource | None = None


class NetworkStatusThresholdsRead(BaseModel):
    """Los umbrales con que el backend calcula el estado; el frontend los usa para colorear el historial."""

    latency_warning_ms: float
    latency_critical_ms: float
    packet_loss_warning_percent: float
    packet_loss_critical_percent: float


class NetworkMetricSampleRead(BaseModel):
    timestamp: datetime
    latency_ms: float
    # Campo agregado: el gráfico clasifica por latencia y pérdida, como el estado; los clientes anteriores lo ignoran.
    packet_loss_percent: float


class NetworkMetricSnapshotCreate(BaseModel):
    """Snapshot real a registrar; solo un admin puede pasar el owner_id de otro usuario."""

    owner_id: uuid.UUID | None = None
    latency_ms: float
    jitter_ms: float
    packet_loss_percent: float
    source: MeasurementSource = DEFAULT_MEASUREMENT_SOURCE
    recorded_at: datetime | None = None
    # SHA-256 de la MAC del router calculado en el escritorio: la MAC cruda nunca llega aquí. None desde la web.
    network_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
