import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings
from app.domain.measurement_source import DEFAULT_MEASUREMENT_SOURCE, MeasurementSource
from app.domain.measurement_timing import as_utc
from app.domain.network_diagnosis import NetworkDiagnosis
from app.domain.network_status import NetworkStatus


class NetworkMetricSnapshotRead(BaseModel):
    status: NetworkStatus
    latency_ms: float
    jitter_ms: float
    packet_loss_percent: float
    updated_at: datetime
    # El frontend rotula la web como "latencia al servidor"; None mientras no haya mediciones.
    source: MeasurementSource | None = None
    # Campos agregados (opcionales, los clientes anteriores los ignoran). Solo GET /latest trae el diagnóstico.
    gateway_latency_ms: float | None = None
    diagnosis: NetworkDiagnosis | None = None
    possible_busy_device: bool | None = None


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
    # Hora original de la medición (la cola del cliente reenvía tarde). Sin ella se usa la del servidor, como antes.
    # Con ella, reenviar la misma medición no la duplica.
    recorded_at: datetime | None = None
    # Hora del reloj del cliente al enviar. Con ella se corrige recorded_at al reloj del servidor, así un PC con la hora
    # mal puesta no pierde mediciones ni las hace parecer atrasadas.
    sent_at: datetime | None = None
    # Latencia al router medida por el escritorio desde 0.1.6. Sin ella no hay diagnóstico router / proveedor.
    gateway_latency_ms: float | None = Field(default=None, ge=0)
    # SHA-256 de la MAC del router calculado en el escritorio: la MAC cruda nunca llega aquí. None desde la web.
    network_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _recorded_at_on_server_clock(self) -> "NetworkMetricSnapshotCreate":
        if self.recorded_at is None:
            return self
        policy = get_settings().measurement_timing_policy
        now = datetime.now(UTC)
        recorded_at = as_utc(self.recorded_at)
        if self.sent_at is not None:
            recorded_at = policy.to_server_clock(recorded_at, as_utc(self.sent_at), now)
        reason = policy.rejection_reason(recorded_at, now)
        if reason is not None:
            raise ValueError(reason)
        self.recorded_at = recorded_at
        return self
