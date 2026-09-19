"""Chequeo minimo sin DB/red: valida filtrado por owner, "nuevas desde X" y acknowledge."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.alert import Alert
from app.repositories.alert_repository import AlertRepository
from app.schemas.alert import AlertCreate
from app.services.alert_service import AlertNotFoundError, AlertService


class FakeAlertRepository(AlertRepository):
    def __init__(self) -> None:
        self.alerts: dict[uuid.UUID, Alert] = {}

    def list_all(self, owner_id: uuid.UUID) -> list[Alert]:
        owned = [a for a in self.alerts.values() if a.owner_id == owner_id]
        return sorted(owned, key=lambda a: a.created_at, reverse=True)

    def list_new_since(self, owner_id: uuid.UUID, since: datetime) -> list[Alert]:
        owned = [a for a in self.alerts.values() if a.owner_id == owner_id and a.created_at > since]
        return sorted(owned, key=lambda a: a.created_at)

    def count_unacknowledged_all(self) -> int:
        return sum(1 for a in self.alerts.values() if not a.acknowledged)

    def get_by_id(self, alert_id: uuid.UUID, owner_id: uuid.UUID) -> Alert | None:
        alert = self.alerts.get(alert_id)
        return alert if alert and alert.owner_id == owner_id else None

    def acknowledge(self, alert_id: uuid.UUID, owner_id: uuid.UUID) -> Alert | None:
        alert = self.get_by_id(alert_id, owner_id)
        if alert is None:
            return None
        alert.acknowledged = True
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
            id=uuid.uuid4(),
            owner_id=owner_id,
            type=type_,
            severity=severity,
            message_key=message_key,
            message_params=message_params,
            created_at=created_at or datetime.now(timezone.utc),
            acknowledged=False,
        )
        self.alerts[alert.id] = alert
        return alert


def test_list_new_alerts_only_returns_alerts_after_since_for_that_owner() -> None:
    repository = FakeAlertRepository()
    service = AlertService(repository)
    owner_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    old_alert = service.create_alert(
        AlertCreate(owner_id=owner_id, type="outage", severity="warning", message_key="a", created_at=now - timedelta(hours=2))
    )
    new_alert = service.create_alert(
        AlertCreate(owner_id=owner_id, type="prediction", severity="info", message_key="b", created_at=now)
    )
    service.create_alert(
        AlertCreate(owner_id=uuid.uuid4(), type="outage", severity="critical", message_key="c", created_at=now)
    )

    result = service.list_new_alerts(owner_id, since=now - timedelta(hours=1))

    assert [a.id for a in result] == [new_alert.id]
    assert old_alert.id not in [a.id for a in result]


def test_acknowledge_alert_marks_it_and_persists() -> None:
    repository = FakeAlertRepository()
    service = AlertService(repository)
    owner_id = uuid.uuid4()
    alert = service.create_alert(
        AlertCreate(owner_id=owner_id, type="outage", severity="critical", message_key="x")
    )

    updated = service.acknowledge_alert(alert.id, owner_id)

    assert updated.acknowledged is True


def test_acknowledge_alert_of_another_owner_raises_not_found() -> None:
    repository = FakeAlertRepository()
    service = AlertService(repository)
    alert = service.create_alert(
        AlertCreate(owner_id=uuid.uuid4(), type="outage", severity="info", message_key="x")
    )

    try:
        service.acknowledge_alert(alert.id, uuid.uuid4())
        raise AssertionError("expected AlertNotFoundError")
    except AlertNotFoundError:
        pass


if __name__ == "__main__":
    test_list_new_alerts_only_returns_alerts_after_since_for_that_owner()
    test_acknowledge_alert_marks_it_and_persists()
    test_acknowledge_alert_of_another_owner_raises_not_found()
    print("OK")
