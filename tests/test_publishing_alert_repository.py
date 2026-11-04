"""Cada alerta guardada (detectores, escaneo o la de prueba) se publica como alert.created ya con su commit."""

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.alert import Alert
from app.models.base import Base
from app.models.role import Role
from app.models.user import User
from app.realtime.events import RealtimeEvent
from app.repositories.publishing_alert_repository import PublishingAlertRepository

OWNER_ID = uuid.uuid4()


class _CapturingPublisher:
    def __init__(self) -> None:
        self.events: list[RealtimeEvent] = []

    def publish(self, event: RealtimeEvent) -> None:
        self.events.append(event)


def test_a_created_alert_is_saved_and_then_published_with_the_rest_shape() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        db.add_all([Role(id=1, name="standard"), User(id=OWNER_ID, email="owner@example.com", role_id=1)])
        db.commit()
    publisher = _CapturingPublisher()

    with session_factory() as db:
        alert = PublishingAlertRepository(db, publisher).create(
            owner_id=OWNER_ID,
            type_="outage",
            severity="critical",
            message_key="user.alertsCenter.briefOutage",
            message_params={"minutes": 5},
            created_at=None,
        )
    with session_factory() as db:
        stored = db.get(Alert, alert.id)

    [event] = publisher.events
    assert stored is not None
    assert (event.type, event.owner_id) == ("alert.created", OWNER_ID)
    assert event.data["id"] == str(alert.id)
    assert set(event.data) == {"id", "type", "severity", "message_key", "message_params", "timestamp", "acknowledged"}
    Base.metadata.drop_all(engine)
