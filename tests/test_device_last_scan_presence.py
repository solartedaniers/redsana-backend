"""Conectado es lo que vio el último escaneo: todos los equipos de un mismo sync guardan el mismo last_seen, y un equipo
que deja de aparecer baja del conteo en /devices, en el diagnóstico y en la supervisión del admin, sin reaparecer."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.device_presence import NON_MEMBER_ROLES, count_connected_members, is_device_online, latest_seen_among
from app.models.base import Base
from app.repositories.device_repository import DeviceRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.schemas.device import DeviceSyncItem
from app.services import device_service
from app.services.device_service import DeviceService

FIRST_SCAN_AT = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


class _Clock:
    """Reemplaza a datetime en device_service: cada escaneo ocurre cuando la prueba dice."""

    current = FIRST_SCAN_AT

    @classmethod
    def now(cls, tz=None):
        return cls.current


@pytest.fixture()
def session_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(device_service, "datetime", _Clock)
    _Clock.current = FIRST_SCAN_AT
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _scan(mac_suffixes: range | list[int]) -> list[DeviceSyncItem]:
    roles = {1: "gateway", 2: "this_device"}
    return [
        DeviceSyncItem(
            mac_address=f"aa-aa-aa-aa-{n // 256:02x}-{n % 256:02x}",
            ip_address=f"10.0.{n // 256}.{n % 256}",
            role=roles.get(n, "other"),
        )
        for n in mac_suffixes
    ]


def _sync_at(session_factory, owner_id: uuid.UUID, when: datetime, devices: list[DeviceSyncItem]) -> None:
    _Clock.current = when
    with session_factory() as db:
        DeviceService(SqlAlchemyDeviceRepository(db)).sync_discovered_devices(owner_id, devices)


def _counts(session_factory, owner_id: uuid.UUID) -> dict[str, int]:
    """Lo que daría cada pantalla, leído de una sesión nueva como al volver a abrirla."""
    with session_factory() as db:
        repository = SqlAlchemyDeviceRepository(db)
        devices = repository.list_by_owner(owner_id)
        latest_seen = latest_seen_among(devices)
        listed = [d for d in devices if is_device_online(d, latest_seen) and d.network_role not in NON_MEMBER_ROLES]
        return {
            "devices_screen": len(listed),
            "diagnosis_and_admin_sql": repository.count_connected_members_by_owners([owner_id])[owner_id].members,
            "generic_rule": DeviceRepository.count_connected_members_by_owners(repository, [owner_id])[
                owner_id
            ].members,
            "domain": count_connected_members(devices).members,
        }


def test_every_device_of_one_sync_keeps_exactly_the_same_last_seen(session_factory) -> None:
    owner_id = uuid.uuid4()
    _sync_at(session_factory, owner_id, FIRST_SCAN_AT, _scan(range(1, 301)))
    # El segundo escaneo actualiza 300 conocidos y crea 300 nuevos en el mismo sync.
    second_scan_at = FIRST_SCAN_AT + timedelta(minutes=1, microseconds=123_456)
    _sync_at(session_factory, owner_id, second_scan_at, _scan(range(1, 601)))

    with session_factory() as db:
        stored = {
            device.last_seen.replace(tzinfo=device.last_seen.tzinfo or UTC)
            for device in SqlAlchemyDeviceRepository(db).list_by_owner(owner_id)
        }
    assert stored == {second_scan_at}
    assert set(_counts(session_factory, owner_id).values()) == {598}  # sin el router ni este equipo


@pytest.mark.parametrize("seconds_between_scans", [1, 10, 29, 600])
def test_devices_that_leave_drop_out_and_do_not_come_back_when_reopening(
    session_factory, seconds_between_scans
) -> None:
    owner_id = uuid.uuid4()
    _sync_at(session_factory, owner_id, FIRST_SCAN_AT, _scan(range(1, 11)))
    assert set(_counts(session_factory, owner_id).values()) == {8}

    later = FIRST_SCAN_AT + timedelta(seconds=seconds_between_scans)
    _sync_at(session_factory, owner_id, later, _scan([1, 2, 3, 4, 5]))

    assert _counts(session_factory, owner_id) == dict.fromkeys(_counts(session_factory, owner_id), 3)
    # Volver a la pantalla sin escanear de nuevo no los trae de vuelta.
    assert set(_counts(session_factory, owner_id).values()) == {3}
