import uuid
from dataclasses import dataclass
from datetime import datetime

from app.domain.network_status import NetworkStatus
from app.domain.security_score import compute_security_score
from app.models.user import User
from app.repositories.alert_repository import AlertRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.network_metrics_repository import NetworkMetricsRepository
from app.repositories.user_repository import UserRepository

STANDARD_ROLE_NAME = "standard"
TRUSTED_DEVICE_TRUST_VALUE = "trusted"


@dataclass
class MonitoredHousehold:
    """Proyeccion de solo lectura para supervision de admin: no existe una tabla
    de "hogares" propia, cada usuario estandar es un hogar."""

    id: uuid.UUID
    owner_name: str
    label: str
    status: NetworkStatus
    security_score: int
    last_activity: datetime


class NetworkSupervisionService:
    def __init__(
        self,
        user_repository: UserRepository,
        device_repository: DeviceRepository,
        alert_repository: AlertRepository,
        network_metrics_repository: NetworkMetricsRepository,
    ) -> None:
        self._user_repository = user_repository
        self._device_repository = device_repository
        self._alert_repository = alert_repository
        self._network_metrics_repository = network_metrics_repository

    def list_households(self) -> list[MonitoredHousehold]:
        owners = [user for user in self._user_repository.list_all() if user.role.name == STANDARD_ROLE_NAME]
        return [self._to_household(owner) for owner in owners]

    def _to_household(self, owner: User) -> MonitoredHousehold:
        devices = self._device_repository.list_by_owner(owner.id)
        trusted_ratio = None
        if devices:
            trusted_count = sum(1 for device in devices if device.trust == TRUSTED_DEVICE_TRUST_VALUE)
            trusted_ratio = trusted_count / len(devices)

        alerts = self._alert_repository.list_all(owner.id)
        unacknowledged_count = sum(1 for alert in alerts if not alert.acknowledged)

        latest_snapshot = self._network_metrics_repository.get_latest(owner.id)
        status: NetworkStatus = latest_snapshot.status if latest_snapshot is not None else "unknown"
        last_activity = latest_snapshot.recorded_at if latest_snapshot is not None else owner.created_at

        security_score = compute_security_score(trusted_ratio, unacknowledged_count, status)

        return MonitoredHousehold(
            id=owner.id,
            owner_name=owner.full_name or owner.email,
            label=owner.email,
            status=status,
            security_score=security_score,
            last_activity=last_activity,
        )
