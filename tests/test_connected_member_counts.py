"""Contar en SQL los miembros conectados da lo mismo que connected_members sobre la lista completa, y /latest ya no trae
los dispositivos del dueño: una cuenta de prueba tiene 1849."""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import get_current_claims
from app.domain.device_presence import DEVICE_PRESENCE_TOLERANCE
from app.domain.device_role import DEVICE_ROLE_VALUES
from app.main import app
from app.models.base import Base
from app.models.device import DEVICE_TRUST_VALUES, Device
from app.models.role import Role
from app.models.user import User
from app.repositories.device_repository import DeviceRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository

OWNER_ID = uuid.uuid4()
CAMPUS_DEVICES = 1849
SCAN_AT = datetime(2026, 11, 4, 12, 0, 0, 123456, tzinfo=UTC)
ONE_MICROSECOND = timedelta(microseconds=1)
# Dos en el último escaneo (justo en el borde), uno justo fuera y escaneos anteriores.
OFFSETS = (
    timedelta(0),
    DEVICE_PRESENCE_TOLERANCE,
    DEVICE_PRESENCE_TOLERANCE + ONE_MICROSECOND,
    timedelta(seconds=30),
    timedelta(hours=1),
)
ROLES = (None, *DEVICE_ROLE_VALUES)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
        db.commit()
    yield factory
    Base.metadata.drop_all(engine)


def _device(owner_id: uuid.UUID, index: int, last_seen: datetime, role: str | None, trust: str) -> Device:
    return Device(
        owner_id=owner_id,
        name="",
        mac_address=f"aa-bb-cc-{index >> 16 & 0xFF:02x}-{index >> 8 & 0xFF:02x}-{index & 0xFF:02x}",
        ip_address=f"10.0.{index >> 8 & 0xFF}.{index & 0xFF}",
        trust=trust,
        network_role=role,
        first_seen=last_seen,
        last_seen=last_seen,
    )


def _old_counts(repository: SqlAlchemyDeviceRepository, owner_ids: list[uuid.UUID]) -> dict:
    """La lógica de antes: traer todos los dispositivos y aplicar connected_members en Python."""
    return DeviceRepository.count_connected_members_by_owners(repository, owner_ids)


def test_counting_in_sql_matches_connected_members_on_fixed_data(session_factory) -> None:
    rng = random.Random(20261104)
    owners = [uuid.uuid4() for _ in range(4)]
    no_devices = uuid.uuid4()
    with session_factory() as db:
        devices = [
            _device(
                owner_id,
                index,
                SCAN_AT - rng.choice(OFFSETS) + timedelta(minutes=owner_number),
                rng.choice(ROLES),
                rng.choice(DEVICE_TRUST_VALUES),
            )
            for owner_number, owner_id in enumerate(owners)
            for index in range(owner_number * 1000, owner_number * 1000 + 300)
        ]
        # Un dueño cuyo último visto es solo el router: el resto quedó fuera de la tolerancia.
        devices.append(_device(owners[0], 9000, SCAN_AT + timedelta(hours=2), "gateway", "trusted"))
        db.add_all(devices)
        db.commit()

    with session_factory() as db:
        repository = SqlAlchemyDeviceRepository(db)
        owner_ids = [*owners, no_devices]
        new = repository.count_connected_members_by_owners(owner_ids)
        old = _old_counts(repository, owner_ids)

    assert new == old
    assert new[no_devices].members == 0
    assert new[owners[0]].members == 0
    assert any(counts.members and counts.trusted for counts in new.values())


def test_the_border_of_the_tolerance_is_counted_like_before(session_factory) -> None:
    with session_factory() as db:
        db.add_all(
            _device(OWNER_ID, index, SCAN_AT - offset, "other", "trusted") for index, offset in enumerate(OFFSETS)
        )
        db.commit()

    with session_factory() as db:
        repository = SqlAlchemyDeviceRepository(db)
        counts = repository.count_connected_members_by_owners([OWNER_ID])

        assert counts == _old_counts(repository, [OWNER_ID])
    assert counts[OWNER_ID].members == 2  # solo los dos del último escaneo


@pytest.fixture()
def client(session_factory, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.routers.network_metrics.SessionLocal", session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: {"sub": str(OWNER_ID), "email": "owner@example.com"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_latest_counts_the_1849_campus_devices_without_loading_them(client: TestClient, session_factory) -> None:
    now = datetime.now(UTC)
    with session_factory() as db:
        db.add(User(id=OWNER_ID, email="owner@example.com", role_id=1))
        db.add_all(_device(OWNER_ID, index, now, "other", "unknown") for index in range(CAMPUS_DEVICES))
        db.commit()
    measurement = {"latency_ms": 20, "jitter_ms": 2, "packet_loss_percent": 0, "source": "native"}
    assert client.post("/api/network-metrics", json={**measurement, "gateway_latency_ms": 150}).status_code == 201

    statements: list[str] = []
    loaded_devices: list[Device] = []
    engine = session_factory.kw["bind"]

    def capture_statement(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    def capture_loaded(_session, instance) -> None:
        if isinstance(instance, Device):
            loaded_devices.append(instance)

    event.listen(engine, "before_cursor_execute", capture_statement)
    event.listen(session_factory, "loaded_as_persistent", capture_loaded)
    try:
        latest = client.get("/api/network-metrics/latest").json()
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)
        event.remove(session_factory, "loaded_as_persistent", capture_loaded)

    assert latest["diagnosis"] == "router"
    assert latest["possible_busy_device"] is True
    assert loaded_devices == []
    assert not [statement for statement in statements if "devices.mac_address" in statement]
