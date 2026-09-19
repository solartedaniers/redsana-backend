from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.authorization import require_admin
from app.core.database import get_db
from app.models.user import User
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.schemas.admin import AdminPlatformMetricsRead
from app.services.admin_metrics_service import AdminMetricsService
from app.services.network_supervision_service import NetworkSupervisionService

router = APIRouter(prefix="/api/admin/metrics", tags=["admin"])


@router.get("", response_model=AdminPlatformMetricsRead)
def get_platform_metrics(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminPlatformMetricsRead:
    user_repository = SqlAlchemyUserRepository(db)
    alert_repository = SqlAlchemyAlertRepository(db)
    network_supervision_service = NetworkSupervisionService(
        user_repository=user_repository,
        device_repository=SqlAlchemyDeviceRepository(db),
        alert_repository=alert_repository,
        network_metrics_repository=SqlAlchemyNetworkMetricsRepository(db),
    )
    service = AdminMetricsService(user_repository, alert_repository, network_supervision_service)
    metrics = service.get_platform_metrics()
    return AdminPlatformMetricsRead(
        total_users=metrics.total_users,
        monitored_households=metrics.monitored_households,
        active_alerts=metrics.active_alerts,
        average_security_score=metrics.average_security_score,
    )
