import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.repositories.alert_repository import AlertRepository


class SqlAlchemyAlertRepository(AlertRepository):
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_all(self, owner_id: uuid.UUID) -> list[Alert]:
        stmt = (
            select(Alert).where(Alert.owner_id == owner_id).order_by(Alert.created_at.desc())
        )
        return list(self._db.scalars(stmt).all())

    def list_by_owners(self, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Alert]]:
        if not owner_ids:
            return {}
        stmt = select(Alert).where(Alert.owner_id.in_(owner_ids))
        result: dict[uuid.UUID, list[Alert]] = {owner_id: [] for owner_id in owner_ids}
        for alert in self._db.scalars(stmt).all():
            result[alert.owner_id].append(alert)
        return result

    def count_unacknowledged_all(self) -> int:
        stmt = select(func.count()).select_from(Alert).where(Alert.acknowledged.is_(False))
        return self._db.scalar(stmt) or 0

    def list_new_since(self, owner_id: uuid.UUID, since: datetime) -> list[Alert]:
        stmt = (
            select(Alert)
            .where(Alert.owner_id == owner_id, Alert.created_at > since)
            .order_by(Alert.created_at.asc())
        )
        return list(self._db.scalars(stmt).all())

    def get_by_id(self, alert_id: uuid.UUID, owner_id: uuid.UUID) -> Alert | None:
        stmt = select(Alert).where(Alert.id == alert_id, Alert.owner_id == owner_id)
        return self._db.scalars(stmt).first()

    def get_latest_unacknowledged(self, owner_id: uuid.UUID, type_: str) -> Alert | None:
        stmt = (
            select(Alert)
            .where(Alert.owner_id == owner_id, Alert.type == type_, Alert.acknowledged.is_(False))
            .order_by(Alert.created_at.desc())
            .limit(1)
        )
        return self._db.scalars(stmt).first()

    def acknowledge(self, alert_id: uuid.UUID, owner_id: uuid.UUID) -> Alert | None:
        alert = self.get_by_id(alert_id, owner_id)
        if alert is None:
            return None

        alert.acknowledged = True
        self._db.commit()
        self._db.refresh(alert)
        return alert

    def create(
        self,
        owner_id: uuid.UUID,
        type_: str,
        severity: str,
        message_key: str,
        message_params: dict | None,
        created_at: datetime | None,
    ) -> Alert:
        alert = Alert(
            owner_id=owner_id,
            type=type_,
            severity=severity,
            message_key=message_key,
            message_params=message_params,
        )
        if created_at is not None:
            alert.created_at = created_at

        self._db.add(alert)
        self._db.commit()
        self._db.refresh(alert)
        return alert
