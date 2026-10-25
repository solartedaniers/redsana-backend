"""Los UUID se leen igual en SQLite aunque su hex parezca un número. Con postgresql.UUID la columna quedaba con afinidad
NUMERIC y SQLite guardaba "123...e5..." como real: uuid.UUID(float) fallaba al azar (1 de cada ~10^6 ids)."""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.role import Role
from app.models.user import User

NUMBER_LOOKING_IDS = [
    pytest.param("12345678-1234-4234-8234-1234567e8901", id="digitos-y-una-e"),
    pytest.param("12345678-1234-4234-8234-123456789012", id="solo-digitos"),
]


@pytest.mark.parametrize("raw", NUMBER_LOOKING_IDS)
def test_a_number_looking_uuid_round_trips(raw: str) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    owner_id = uuid.UUID(raw)
    with Session(engine) as db:
        db.add_all([Role(id=1, name="standard"), User(id=owner_id, email="a@example.com", role_id=1)])
        db.flush()
        db.add(
            NetworkMetricSnapshot(
                id=owner_id, owner_id=owner_id, latency_ms=1, jitter_ms=0, packet_loss_percent=0, status="good"
            )
        )
        db.commit()

    with Session(engine) as db:
        assert db.scalars(select(User.id)).one() == owner_id
        assert db.execute(select(NetworkMetricSnapshot.id, NetworkMetricSnapshot.owner_id)).one() == (owner_id, owner_id)
