"""E2E a nivel de router (SQLite en memoria): marcar un dispositivo como
confiable/inseguro solo cambia `trust`; no mueve last_seen ni la presencia del
resto (ya pasó: el onupdate de last_seen desconectaba a todos los demás)."""
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
        # Los dos los vio el mismo escaneo (mismo last_seen): ambos "en línea".
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
    # Ningún dispositivo quedó "desconectado" por el cambio de confianza.
    assert all(device["is_online"] for device in after.values())


def test_last_seen_cannot_be_set_through_the_update_endpoint(setup) -> None:
    client, (marked_id, _) = setup
    before = _devices(client)[marked_id]["last_seen"]

    client.patch(f"/api/devices/{marked_id}", json={"trust": "trusted", "last_seen": "2030-01-01T00:00:00Z"})

    assert _devices(client)[marked_id]["last_seen"] == before
