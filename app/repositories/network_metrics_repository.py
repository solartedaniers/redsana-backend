import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from app.domain.measurement_source import MeasurementSource
from app.domain.network_baseline import BaselineScope
from app.models.network_metric_snapshot import NetworkMetricSnapshot


class NetworkMetricsRepository(ABC):
    @abstractmethod
    def get_latest(self, owner_id: uuid.UUID) -> NetworkMetricSnapshot | None: ...

    @abstractmethod
    def get_latest_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, NetworkMetricSnapshot]:
        """El snapshot más reciente de cada dueño en una sola consulta."""
        ...

    @abstractmethod
    def list_in_range(self, owner_id: uuid.UUID, start: datetime, end: datetime) -> list[NetworkMetricSnapshot]: ...

    @abstractmethod
    def list_latest(
        self, owner_id: uuid.UUID, limit: int, scope: BaselineScope | None = None
    ) -> list[NetworkMetricSnapshot]:
        """Las `limit` muestras más recientes, la más nueva primero; `scope` filtra por fuente y red (None = todas)."""
        ...

    @abstractmethod
    def find_recorded_near(
        self, owner_id: uuid.UUID, source: MeasurementSource, recorded_at: datetime, tolerance: timedelta
    ) -> NetworkMetricSnapshot | None:
        """La medición ya guardada a menos de `tolerance` de esa hora: así un reenvío de la cola no la duplica."""
        ...

    @abstractmethod
    def last_gateway_reply_at(self, owner_id: uuid.UUID, until: datetime) -> datetime | None:
        """Hora de la medición más reciente, hasta `until`, en que el router respondió al ping (solo escritorio)."""
        ...

    @abstractmethod
    def count_by_owner(self, owner_id: uuid.UUID, scope: BaselineScope | None = None) -> int: ...

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
        network_id: str | None = None,
        gateway_latency_ms: float | None = None,
    ) -> NetworkMetricSnapshot: ...
