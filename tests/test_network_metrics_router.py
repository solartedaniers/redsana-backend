"""E2E a nivel de router: valida el nuevo modelo de permisos del POST usando
la app real (autorizacion + servicio + repositorio reales), con SQLite en
memoria y el token ya "decodificado" via dependency_overrides (una firma JWT
real de Supabase no es verificable offline)."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.role import Role

OWNER_USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()


def _sqlite_session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session_factory() as db:
        db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
        db.commit()

    return engine, session_factory


@pytest.fixture()
def client():
    """Cliente con el token ya "decodificado" (overridea get_current_claims):
    usado para probar la logica de autorizacion propia del router."""
    engine, session_factory = _sqlite_session_factory()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_claims():
        return {"sub": str(OWNER_USER_ID), "email": "owner@example.com"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = override_get_current_claims
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client_without_claims_override():
    """Cliente que deja correr el HTTPBearer real: sirve para probar el caso
    sin token, sin overridear get_current_claims (evita el fetch de JWKS
    porque nunca llega a decodificar nada sin Authorization header)."""
    engine, session_factory = _sqlite_session_factory()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


SNAPSHOT_PAYLOAD = {"latency_ms": 20, "jitter_ms": 2, "packet_loss_percent": 0}


def test_standard_user_can_insert_own_snapshot(client: TestClient) -> None:
    response = client.post(
        "/api/network-metrics", json=SNAPSHOT_PAYLOAD, headers={"Authorization": "Bearer fake"}
    )

    assert response.status_code == 201
    latest = client.get(
        "/api/network-metrics/latest", headers={"Authorization": "Bearer fake"}
    )
    assert latest.status_code == 200
    assert latest.json()["latency_ms"] == SNAPSHOT_PAYLOAD["latency_ms"]


def test_standard_user_cannot_insert_snapshot_for_another_user(client: TestClient) -> None:
    response = client.post(
        "/api/network-metrics",
        json={**SNAPSHOT_PAYLOAD, "owner_id": str(OTHER_USER_ID)},
        headers={"Authorization": "Bearer fake"},
    )

    assert response.status_code == 403


def test_post_without_token_is_unauthorized(client_without_claims_override: TestClient) -> None:
    response = client_without_claims_override.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD)

    assert response.status_code == 401


if __name__ == "__main__":
    print("Run via pytest: python -m pytest tests/test_network_metrics_router.py")
