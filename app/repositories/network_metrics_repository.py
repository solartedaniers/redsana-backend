import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.measurement_source import MeasurementSource
from app.models.network_metric_snapshot import NetworkMetricSnapshot


class NetworkMetricsRepository(ABC):
    """Contrato de acceso a datos para snapshots historicos de metricas de red."""

    @abstractmethod
    def get_latest(self, owner_id: uuid.UUID) -> NetworkMetricSnapshot | None: ...

    @abstractmethod
    def get_latest_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, NetworkMetricSnapshot]:
        """El snapshot más reciente de cada owner, en una sola consulta (ej.
        supervision de admin) en vez de get_latest uno por uno."""
        ...

    @abstractmethod
    def list_in_range(self, owner_id: uuid.UUID, start: datetime, end: datetime) -> list[NetworkMetricSnapshot]: ...

    @abstractmethod
    def list_latest(
        self, owner_id: uuid.UUID, limit: int, source: MeasurementSource | None = None
    ) -> list[NetworkMetricSnapshot]:
        """Las `limit` muestras más recientes, más nueva primero; `source` filtra
        por fuente de medición (None = todas, p. ej. para detectar cortes)."""
        ...

    @abstractmethod
    def count_by_owner(self, owner_id: uuid.UUID, source: MeasurementSource | None = None) -> int: ...

    @abstractmethod
    def create(
        self,
        owner_id: uuid.UUID,
        latency_ms: float,
        jitter_ms: float,
        packet_loss_percent: float,
        status: str,
        source: MeasurementSource,
        recorded_at: datetime | None,
    ) -> NetworkMetricSnapshot: ...
