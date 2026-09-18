import uuid
from datetime import datetime

from app.models.alert import Alert
from app.repositories.alert_repository import AlertRepository
from app.schemas.alert import AlertCreate


class AlertNotFoundError(Exception):
    pass


class AlertService:
    def __init__(self, repository: AlertRepository) -> None:
        self._repository = repository

    def list_alerts(self, owner_id: uuid.UUID) -> list[Alert]:
        return self._repository.list_all(owner_id)

    def list_new_alerts(self, owner_id: uuid.UUID, since: datetime) -> list[Alert]:
        return self._repository.list_new_since(owner_id, since)

    def acknowledge_alert(self, alert_id: uuid.UUID, owner_id: uuid.UUID) -> Alert:
        alert = self._repository.acknowledge(alert_id, owner_id)
        if alert is None:
            raise AlertNotFoundError(f"Alert '{alert_id}' does not exist")
        return alert

    def create_alert(self, payload: AlertCreate) -> Alert:
        return self._repository.create(
            owner_id=payload.owner_id,
            type_=payload.type,
            severity=payload.severity,
            message_key=payload.message_key,
            message_params=payload.message_params,
            created_at=payload.created_at,
        )
