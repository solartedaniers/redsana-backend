import uuid
from dataclasses import dataclass

from app.domain.device_presence import connected_members
from app.domain.measurement_timing import as_utc
from app.domain.network_diagnosis import NetworkDiagnosis, NetworkDiagnosisPolicy
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.device_repository import DeviceRepository
from app.repositories.network_metrics_repository import NetworkMetricsRepository


@dataclass(frozen=True)
class NetworkDiagnosisResult:
    diagnosis: NetworkDiagnosis | None
    possible_busy_device: bool | None


class NetworkDiagnosisService:
    """Aplica la regla a la última medición; los dispositivos conectados son los mismos que cuenta la pantalla."""

    def __init__(
        self,
        device_repository: DeviceRepository,
        metrics_repository: NetworkMetricsRepository,
        policy: NetworkDiagnosisPolicy,
    ) -> None:
        self._device_repository = device_repository
        self._metrics_repository = metrics_repository
        self._policy = policy

    def describe(self, owner_id: uuid.UUID, snapshot: NetworkMetricSnapshot) -> NetworkDiagnosisResult:
        gateway_latency_ms = snapshot.gateway_latency_ms
        if gateway_latency_ms is None:
            return NetworkDiagnosisResult(
                diagnosis=self._diagnose_without_router(owner_id, snapshot), possible_busy_device=None
            )
        connected = len(connected_members(self._device_repository.list_by_owner(owner_id)))
        return NetworkDiagnosisResult(
            diagnosis=self._policy.diagnose(snapshot.status, gateway_latency_ms),
            possible_busy_device=self._policy.possible_busy_device(gateway_latency_ms, connected),
        )

    def _diagnose_without_router(self, owner_id: uuid.UUID, snapshot: NetworkMetricSnapshot) -> NetworkDiagnosis | None:
        # La web nunca mide el router: una medición suya sin router no dice nada de él.
        if snapshot.source != "native":
            return None
        # La consulta usa la hora tal como está guardada (SQLite la guarda sin zona); la cuenta, en UTC.
        last_reply = self._metrics_repository.last_gateway_reply_at(owner_id, snapshot.recorded_at)
        measured_at = as_utc(snapshot.recorded_at)
        return self._policy.diagnose(
            snapshot.status,
            None,
            packet_loss_percent=snapshot.packet_loss_percent,
            router_replied_recently=self._policy.router_replied_recently(
                as_utc(last_reply) if last_reply else None, measured_at
            ),
        )
