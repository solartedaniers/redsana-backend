import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.authorization import require_admin
from app.core.database import get_db
from app.core.security import get_current_claims
from app.models.alert import Alert
from app.models.user import User
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.schemas.alert import AlertCreate, AlertRead
from app.services.alert_service import AlertNotFoundError, AlertService

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _owner_id(claims: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(claims["sub"])


def _to_alert_read(alert: Alert) -> AlertRead:
    return AlertRead(
        id=alert.id,
        type=alert.type,
        severity=alert.severity,
        message_key=alert.message_key,
        message_params=alert.message_params,
        timestamp=alert.created_at,
        acknowledged=alert.acknowledged,
    )


@router.get("", response_model=list[AlertRead])
def list_alerts(
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> list[AlertRead]:
    service = AlertService(SqlAlchemyAlertRepository(db))
    alerts = service.list_alerts(_owner_id(claims))
    return [_to_alert_read(alert) for alert in alerts]


@router.get("/new", response_model=list[AlertRead])
def list_new_alerts(
    since: datetime = Query(...),
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> list[AlertRead]:
    service = AlertService(SqlAlchemyAlertRepository(db))
    alerts = service.list_new_alerts(_owner_id(claims), since)
    return [_to_alert_read(alert) for alert in alerts]


@router.patch("/{alert_id}/acknowledge", response_model=AlertRead)
def acknowledge_alert(
    alert_id: uuid.UUID,
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> AlertRead:
    service = AlertService(SqlAlchemyAlertRepository(db))
    try:
        alert = service.acknowledge_alert(alert_id, _owner_id(claims))
    except AlertNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found") from error
    return _to_alert_read(alert)


@router.post("", response_model=AlertRead, status_code=status.HTTP_201_CREATED)
def create_alert(
    payload: AlertCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AlertRead:
    """Endpoint admin para insertar alertas de prueba, mientras no exista un
    proceso real que las genere (llegara con el modulo de IA)."""
    service = AlertService(SqlAlchemyAlertRepository(db))
    alert = service.create_alert(payload)
    return _to_alert_read(alert)
