from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.authorization import require_admin
from app.core.database import get_db
from app.models.user import User
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.repositories.security_assessment_sqlalchemy_repository import SqlAlchemySecurityAssessmentRepository
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.schemas.admin import AdminHouseholdRead
from app.services.network_security_score_service import default_network_security_score_service
from app.services.network_supervision_service import MonitoredHousehold, NetworkSupervisionService

router = APIRouter(prefix="/api/admin/households", tags=["admin"])


def _to_household_read(household: MonitoredHousehold) -> AdminHouseholdRead:
    return AdminHouseholdRead(
        id=household.id,
        owner_name=household.owner_name,
        label=household.label,
        status=household.status,
        security_score=household.security_score,
        security_score_source=household.security_score_source,
        security_score_is_partial=household.security_score_is_partial,
        security_technical_measured_at=household.security_technical_measured_at,
        last_activity=household.last_activity,
    )


@router.get("", response_model=list[AdminHouseholdRead])
def list_households(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminHouseholdRead]:
    service = NetworkSupervisionService(
        user_repository=SqlAlchemyUserRepository(db),
        device_repository=SqlAlchemyDeviceRepository(db),
        alert_repository=SqlAlchemyAlertRepository(db),
        network_metrics_repository=SqlAlchemyNetworkMetricsRepository(db),
        security_assessment_repository=SqlAlchemySecurityAssessmentRepository(db),
        security_score_service=default_network_security_score_service(),
    )
    return [_to_household_read(household) for household in service.list_households()]
