import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.domain.device_presence import connected_members
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
from app.services.technical_evidence_resolver import ResolvedTechnicalEvidence, TechnicalEvidenceResolver

STANDARD_ROLE_NAME = "standard"
TRUSTED_DEVICE_TRUST_VALUE = "trusted"

SecurityScoreSource = Literal["real", "estimated"]


@dataclass(frozen=True)
class HouseholdSecurityScore:
    score: int
    source: SecurityScoreSource
    # Mismo criterio que la pantalla del usuario: real sin evidencia técnica medida.
    is_partial: bool
    # Fecha de la medición técnica solo cuando se reutilizó de una evaluación anterior.
    reused_technical_measured_at: datetime | None


@dataclass
class MonitoredHousehold:
    """Vista de solo lectura para el admin; no hay tabla de hogares: cada usuario estándar es un hogar."""

    id: uuid.UUID
    owner_name: str
    label: str
    status: NetworkStatus
    security_score: int
    security_score_source: SecurityScoreSource
    security_score_is_partial: bool
    security_technical_measured_at: datetime | None
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
        self._evidence_resolver = TechnicalEvidenceResolver(security_assessment_repository)

    def list_households(self) -> list[MonitoredHousehold]:
        owners = [user for user in self._user_repository.list_all() if user.role.name == STANDARD_ROLE_NAME]
        owner_ids = [owner.id for owner in owners]

        # 4 consultas en bloque en total en vez de 4 por hogar (antes eran 1 + 4·N).
        devices_by_owner = self._device_repository.list_by_owners(owner_ids)
        alerts_by_owner = self._alert_repository.list_by_owners(owner_ids)
        latest_snapshot_by_owner = self._network_metrics_repository.get_latest_by_owners(owner_ids)
        latest_assessment_by_owner = self._security_assessment_repository.get_latest_by_owners(owner_ids)
        evidence_by_owner = self._evidence_resolver.resolve_latest_by_owners(latest_assessment_by_owner)

        return [
            self._to_household(
                owner,
                devices_by_owner.get(owner.id, []),
                alerts_by_owner.get(owner.id, []),
                latest_snapshot_by_owner.get(owner.id),
                latest_assessment_by_owner.get(owner.id),
                evidence_by_owner.get(owner.id),
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
        resolved_evidence: ResolvedTechnicalEvidence | None,
    ) -> MonitoredHousehold:
        """Pura: solo transforma lo que ya trajo list_households, sin consultar repositorios (por eso no hay N+1)."""
        # Solo lo conectado en el último escaneo: con todo el historial el porcentaje quedaba siempre cerca de 0.
        members = connected_members(devices)
        trusted_ratio = None
        if members:
            trusted_count = sum(1 for device in members if device.trust == TRUSTED_DEVICE_TRUST_VALUE)
            trusted_ratio = trusted_count / len(members)

        unacknowledged_count = sum(1 for alert in alerts if not alert.acknowledged)

        status: NetworkStatus = latest_snapshot.status if latest_snapshot is not None else "unknown"
        last_activity = latest_snapshot.recorded_at if latest_snapshot is not None else owner.created_at

        security = self._resolve_security_score(
            latest_assessment, resolved_evidence, trusted_ratio, unacknowledged_count, status
        )

        return MonitoredHousehold(
            id=owner.id,
            owner_name=owner.full_name or owner.email,
            label=owner.email,
            status=status,
            security_score=security.score,
            security_score_source=security.source,
            security_score_is_partial=security.is_partial,
            security_technical_measured_at=security.reused_technical_measured_at,
            last_activity=last_activity,
        )

    def _resolve_security_score(
        self,
        latest_assessment: SecurityAssessment | None,
        resolved_evidence: ResolvedTechnicalEvidence | None,
        trusted_ratio: float | None,
        unacknowledged_count: int,
        status: NetworkStatus,
    ) -> HouseholdSecurityScore:
        # El puntaje real del cuestionario manda; solo aproximo para quien todavía no lo respondió.
        if latest_assessment is not None and resolved_evidence is not None:
            score = self._security_score_service.evaluate(latest_assessment.answers, resolved_evidence.evidence)
            return HouseholdSecurityScore(
                score=score.score,
                source="real",
                is_partial=score.is_partial,
                reused_technical_measured_at=resolved_evidence.measured_at if resolved_evidence.is_reused else None,
            )
        return HouseholdSecurityScore(
            score=compute_security_score(trusted_ratio, unacknowledged_count, status),
            source="estimated",
            is_partial=False,
            reused_technical_measured_at=None,
        )
