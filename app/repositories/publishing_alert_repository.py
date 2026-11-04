import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.realtime.events import ALERT_CREATED, RealtimeEvent
from app.realtime.publisher import EventPublisher
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.schemas.alert import AlertRead


class PublishingAlertRepository(SqlAlchemyAlertRepository):
    """Igual que SqlAlchemyAlertRepository, y avisa alert.created ya guardada (create hace el commit). Así los
    detectores y el escaneo publican sin saber que el tiempo real existe."""

    def __init__(self, db: Session, publisher: EventPublisher) -> None:
        super().__init__(db)
        self._publisher = publisher

    def create(
        self,
        owner_id: uuid.UUID,
        type_: str,
        severity: str,
        message_key: str,
        message_params: dict | None,
        created_at: datetime | None,
    ) -> Alert:
        alert = super().create(owner_id, type_, severity, message_key, message_params, created_at)
        self._publisher.publish(RealtimeEvent.now(ALERT_CREATED, owner_id, AlertRead.from_alert(alert)))
        return alert
