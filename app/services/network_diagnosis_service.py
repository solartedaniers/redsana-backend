import uuid
from dataclasses import dataclass

from app.domain.device_presence import connected_members
from app.domain.network_diagnosis import NetworkDiagnosis, NetworkDiagnosisPolicy
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.repositories.device_repository import DeviceRepository


@dataclass(frozen=True)
class NetworkDiagnosisResult:
    diagnosis: NetworkDiagnosis | None
    possible_busy_device: bool | None


class NetworkDiagnosisService:
    """Aplica la regla a la última medición; los dispositivos conectados son los mismos que cuenta la pantalla."""

    def __init__(self, device_repository: DeviceRepository, policy: NetworkDiagnosisPolicy) -> None:
        self._device_repository = device_repository
        self._policy = policy

    def describe(self, owner_id: uuid.UUID, snapshot: NetworkMetricSnapshot) -> NetworkDiagnosisResult:
        gateway_latency_ms = snapshot.gateway_latency_ms
        if gateway_latency_ms is None:
            return NetworkDiagnosisResult(diagnosis=None, possible_busy_device=None)
        connected = len(connected_members(self._device_repository.list_by_owner(owner_id)))
        return NetworkDiagnosisResult(
            diagnosis=self._policy.diagnose(snapshot.status, gateway_latency_ms),
            possible_busy_device=self._policy.possible_busy_device(gateway_latency_ms, connected),
        )
