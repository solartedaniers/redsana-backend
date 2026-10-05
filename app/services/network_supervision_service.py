import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.network_status import NetworkStatus
from app.domain.security_score import compute_security_score
from app.models.alert import Alert
from app.models.device import Device
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.security_assessment import SecurityAssessment
from app.models.user import User
from app.repositories.alert_repository import AlertRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.network_metrics_repository import NetworkMetricsRepository
from app.repositories.security_assessment_repository import SecurityAssessmentRepository
from app.repositories.user_repository import UserRepository
from app.services.network_security_score_service import NetworkSecurityScoreService

STANDARD_ROLE_NAME = "standard"
TRUSTED_DEVICE_TRUST_VALUE = "trusted"

SecurityScoreSource = Literal["real", "estimated"]


@dataclass
class MonitoredHousehold:
    """Proyeccion de solo lectura para supervision de admin: no existe una tabla
    de "hogares" propia, cada usuario estandar es un hogar."""

    id: uuid.UUID
    owner_name: str
    label: str
    status: NetworkStatus
    security_score: int
    security_score_source: SecurityScoreSource
    last_activity: datetime


class NetworkSupervisionService:
    def __init__(
        self,
        user_repository: UserRepository,
        device_repository: DeviceRepository,
        alert_repository: AlertRepository,
        network_metrics_repository: NetworkMetricsRepository,
        security_assessment_repository: SecurityAssessmentRepository,
        security_score_service: NetworkSecurityScoreService,
    ) -> None:
        self._user_repository = user_repository
        self._device_repository = device_repository
        self._alert_repository = alert_repository
        self._network_metrics_repository = network_metrics_repository
        self._security_assessment_repository = security_assessment_repository
        self._security_score_service = security_score_service

    def list_households(self) -> list[MonitoredHousehold]:
        owners = [user for user in self._user_repository.list_all() if user.role.name == STANDARD_ROLE_NAME]
        owner_ids = [owner.id for owner in owners]

        # 4 consultas bulk en total (una por repositorio) en vez de 4 por hogar:
        # antes era 1 + 4*N queries, ahora es 1 + 4 sin importar cuantos hogares haya.
        devices_by_owner = self._device_repository.list_by_owners(owner_ids)
        alerts_by_owner = self._alert_repository.list_by_owners(owner_ids)
        latest_snapshot_by_owner = self._network_metrics_repository.get_latest_by_owners(owner_ids)
        latest_assessment_by_owner = self._security_assessment_repository.get_latest_by_owners(owner_ids)

        return [
            self._to_household(
                owner,
                devices_by_owner.get(owner.id, []),
                alerts_by_owner.get(owner.id, []),
                latest_snapshot_by_owner.get(owner.id),
                latest_assessment_by_owner.get(owner.id),
            )
            for owner in owners
        ]

    def _to_household(
        self,
        owner: User,
        devices: list[Device],
        alerts: list[Alert],
        latest_snapshot: NetworkMetricSnapshot | None,
        latest_assessment: SecurityAssessment | None,
    ) -> MonitoredHousehold:
        """Pura: solo transforma los datos ya traidos por list_households, no
        consulta ningun repositorio (eso es lo que elimina el N+1)."""
        trusted_ratio = None
        if devices:
            trusted_count = sum(1 for device in devices if device.trust == TRUSTED_DEVICE_TRUST_VALUE)
            trusted_ratio = trusted_count / len(devices)

        unacknowledged_count = sum(1 for alert in alerts if not alert.acknowledged)

        status: NetworkStatus = latest_snapshot.status if latest_snapshot is not None else "unknown"
        last_activity = latest_snapshot.recorded_at if latest_snapshot is not None else owner.created_at

        security_score, security_score_source = self._resolve_security_score(
            latest_assessment, trusted_ratio, unacknowledged_count, status
        )

        return MonitoredHousehold(
            id=owner.id,
            owner_name=owner.full_name or owner.email,
            label=owner.email,
            status=status,
            security_score=security_score,
            security_score_source=security_score_source,
            last_activity=last_activity,
        )

    def _resolve_security_score(
        self,
        latest_assessment: SecurityAssessment | None,
        trusted_ratio: float | None,
        unacknowledged_count: int,
        status: NetworkStatus,
    ) -> tuple[int, SecurityScoreSource]:
        # El score real del cuestionario tiene prioridad sobre el proxy: solo se
        # aproxima para los hogares que todavia no lo respondieron.
        if latest_assessment is not None:
            return self._security_score_service.evaluate_assessment(latest_assessment).score, "real"
        return compute_security_score(trusted_ratio, unacknowledged_count, status), "estimated"
