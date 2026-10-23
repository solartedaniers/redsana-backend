"""Cambiar la confianza solo cambia `trust`: antes el onupdate de last_seen desconectaba a todos los demás."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository

OWNER_ID = uuid.uuid4()
SCANNED_AT = datetime.now(timezone.utc) - timedelta(days=3)


@pytest.fixture()
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        repository = SqlAlchemyDeviceRepository(db)
        # Los dos los vio el mismo escaneo: ambos en línea.
        ids = [
            str(repository.create(OWNER_ID, "", mac, ip, "unknown", last_seen=SCANNED_AT).id)
            for mac, ip in (("aa-aa-aa-aa-aa-01", "192.168.0.10"), ("aa-aa-aa-aa-aa-02", "192.168.0.11"))
        ]

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: {"sub": str(OWNER_ID), "email": "owner@example.com"}
    try:
        yield TestClient(app), ids
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _devices(client: TestClient) -> dict[str, dict]:
    return {device["id"]: device for device in client.get("/api/devices").json()}


@pytest.mark.parametrize("trust", ["trusted", "blocked"])
def test_marking_trust_only_changes_the_trust_field(setup, trust: str) -> None:
    client, (marked_id, other_id) = setup
    before = _devices(client)

    response = client.patch(f"/api/devices/{marked_id}", json={"trust": trust})

    assert response.status_code == 200
    after = _devices(client)
    assert after[marked_id]["trust"] == trust
    for device_id in (marked_id, other_id):
        unchanged = {key: value for key, value in after[device_id].items() if key != "trust"}
        assert unchanged == {key: value for key, value in before[device_id].items() if key != "trust"}
    # Ningún dispositivo quedó desconectado por el cambio de confianza.
    assert all(device["is_online"] for device in after.values())


def test_last_seen_cannot_be_set_through_the_update_endpoint(setup) -> None:
    client, (marked_id, _) = setup
    before = _devices(client)[marked_id]["last_seen"]

    client.patch(f"/api/devices/{marked_id}", json={"trust": "trusted", "last_seen": "2030-01-01T00:00:00Z"})

    assert _devices(client)[marked_id]["last_seen"] == before


def _sync(client: TestClient, macs: list[str], **extra) -> dict[str, bool]:
    payload = {"devices": [{"mac_address": mac, "ip_address": "192.168.0.50"} for mac in macs], **extra}
    response = client.post("/api/devices/sync", json=payload)
    assert response.status_code == 200
    return {device["mac_address"]: device["is_online"] for device in response.json()}


def test_sync_without_the_manual_flag_keeps_the_presence_tolerance(setup) -> None:
    client, _ = setup
    _sync(client, ["aa-aa-aa-aa-aa-01", "aa-aa-aa-aa-aa-02"])

    # Lo que envía el instalador 0.1.5 y el escaneo al entrar: el que faltó hace segundos sigue en línea.
    online = _sync(client, ["aa-aa-aa-aa-aa-01"])

    assert online == {"aa-aa-aa-aa-aa-01": True, "aa-aa-aa-aa-aa-02": True}


def test_manual_sync_marks_offline_what_did_not_answer_this_scan(setup) -> None:
    client, _ = setup
    _sync(client, ["aa-aa-aa-aa-aa-01", "aa-aa-aa-aa-aa-02"])

    online = _sync(client, ["aa-aa-aa-aa-aa-01"], manual=True)

    assert online == {"aa-aa-aa-aa-aa-01": True, "aa-aa-aa-aa-aa-02": False}


def test_a_manual_sync_of_450_devices_drops_exactly_the_six_that_left(setup) -> None:
    import time

    client, _ = setup
    campus = [f"02-00-00-00-{index // 256:02x}-{index % 256:02x}" for index in range(450)]
    _sync(client, campus, manual=True)
    leaving = {campus[index] for index in (20, 90, 150, 222, 345, 444)}

    started = time.perf_counter()
    online = _sync(client, [mac for mac in campus if mac not in leaving], manual=True)
    elapsed = time.perf_counter() - started

    offline = {mac for mac, is_online in online.items() if not is_online}
    # Los dos dispositivos del fixture tampoco se vieron en estos escaneos.
    assert offline == leaving | {"aa-aa-aa-aa-aa-01", "aa-aa-aa-aa-aa-02"}
    assert sum(online.values()) == 444
    # Holgado: en SQLite tarda una fracción de segundo; sirve para detectar consultas por dispositivo.
    assert elapsed < 5
