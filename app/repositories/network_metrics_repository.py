import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from app.models.network_metric_snapshot import NetworkMetricSnapshot


class NetworkMetricsRepository(ABC):
    """Contrato de acceso a datos para snapshots historicos de metricas de red."""

    @abstractmethod
    def get_latest(self, owner_id: uuid.UUID) -> NetworkMetricSnapshot | None: ...

    @abstractmethod
    def list_in_range(self, owner_id: uuid.UUID, start: datetime, end: datetime) -> list[NetworkMetricSnapshot]: ...

    @abstractmethod
    def create(
        self,
        owner_id: uuid.UUID,
        latency_ms: float,
        jitter_ms: float,
        packet_loss_percent: float,
        status: str,
        recorded_at: datetime | None,
    ) -> NetworkMetricSnapshot: ...
