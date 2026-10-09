"""Repositorio real en SQLite: last_seen solo se mueve cuando un escaneo ve el dispositivo."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_changing_trust_does_not_touch_last_seen() -> None:
    with _session() as db:
        repository = SqlAlchemyDeviceRepository(db)
        owner_id = uuid.uuid4()
        scanned_at = datetime.now(timezone.utc) - timedelta(days=10)
        device = repository.create(
            owner_id=owner_id, name="", mac_address="aa-bb-cc-dd-ee-ff", ip_address="192.168.1.5",
            trust="unknown", last_seen=scanned_at,
        )

        updated = repository.update(device.id, owner_id, {"trust": "trusted"})

        assert updated.last_seen.replace(tzinfo=timezone.utc) == scanned_at


def test_save_scan_is_all_or_nothing() -> None:
    with _session() as db:
        repository = SqlAlchemyDeviceRepository(db)
        owner_id = uuid.uuid4()
        old_scan = datetime.now(timezone.utc) - timedelta(days=1)
        known = repository.create(
            owner_id=owner_id, name="", mac_address="aa-aa-aa-aa-aa-aa", ip_address="10.0.0.2",
            trust="unknown", last_seen=old_scan,
        )
        new_scan = datetime.now(timezone.utc)
        valid = {"mac_address": "bb-bb-bb-bb-bb-bb", "ip_address": "10.0.0.3", "name": "", "trust": "unknown",
                 "last_seen": new_scan, "first_seen": new_scan}
        clashing = {**valid, "mac_address": known.mac_address}  # rompe la MAC única a mitad del escaneo

        with pytest.raises(IntegrityError):
            repository.save_scan(owner_id, [valid, clashing], {known.id: {"last_seen": new_scan}})
        db.rollback()

        devices = repository.list_by_owner(owner_id)
        assert [d.mac_address for d in devices] == [known.mac_address]
        assert devices[0].last_seen.replace(tzinfo=timezone.utc) == old_scan


def test_save_scan_ignores_updates_for_devices_of_another_owner() -> None:
    with _session() as db:
        repository = SqlAlchemyDeviceRepository(db)
        victim_owner = uuid.uuid4()
        victim = repository.create(
            owner_id=victim_owner, name="", mac_address="aa-aa-aa-aa-aa-aa", ip_address="10.0.0.2", trust="unknown",
        )

        repository.save_scan(uuid.uuid4(), [], {victim.id: {"ip_address": "6.6.6.6"}})

        assert repository.get_by_id(victim.id, victim_owner).ip_address == "10.0.0.2"
