"""Permisos del POST con la app real y SQLite, con el token ya decodificado porque la firma de Supabase no se verifica offline."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
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
def client(monkeypatch: pytest.MonkeyPatch):
    """Cliente con el token ya decodificado, para probar la autorización propia del router."""
    engine, session_factory = _sqlite_session_factory()
    # Las tareas en segundo plano abren su propia sesión: también van a la base de prueba, nunca a la real.
    monkeypatch.setattr("app.routers.network_metrics.SessionLocal", session_factory)

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
    """Cliente con el HTTPBearer real, para el caso sin token (nunca llega a pedir el JWKS)."""
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
    response = client.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD, headers={"Authorization": "Bearer fake"})

    assert response.status_code == 201
    latest = client.get("/api/network-metrics/latest", headers={"Authorization": "Bearer fake"})
    assert latest.status_code == 200
    assert latest.json()["latency_ms"] == SNAPSHOT_PAYLOAD["latency_ms"]


def test_standard_user_cannot_insert_snapshot_for_another_user(client: TestClient) -> None:
    response = client.post(
        "/api/network-metrics",
        json={**SNAPSHOT_PAYLOAD, "owner_id": str(OTHER_USER_ID)},
        headers={"Authorization": "Bearer fake"},
    )

    assert response.status_code == 403


def test_thresholds_endpoint_returns_the_configured_values(client: TestClient) -> None:
    response = client.get("/api/network-metrics/thresholds")

    assert response.status_code == 200
    assert _original_fields(response.json()) == {
        "latency_warning_ms": 80,
        "latency_critical_ms": 150,
        "packet_loss_warning_percent": 1,
        "packet_loss_critical_percent": 5,
    }


def _original_fields(body: dict) -> dict:
    """Los campos que leen la web y el instalador 0.1.5; lo demás solo puede ser agregado y opcional."""
    assert set(body) - ORIGINAL_THRESHOLD_FIELDS <= {"gateway_latency_bad_ms", "gateway_recent_reply_minutes"}
    return {key: body[key] for key in ORIGINAL_THRESHOLD_FIELDS}


ORIGINAL_THRESHOLD_FIELDS = {
    "latency_warning_ms",
    "latency_critical_ms",
    "packet_loss_warning_percent",
    "packet_loss_critical_percent",
}


def test_thresholds_endpoint_follows_the_environment(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_STATUS_LATENCY_CRITICAL_MS", "300")
    get_settings.cache_clear()
    try:
        response = client.get("/api/network-metrics/thresholds")
    finally:
        get_settings.cache_clear()

    assert response.json()["latency_critical_ms"] == 300


def test_thresholds_for_web_use_the_web_latency_scale(client: TestClient) -> None:
    response = client.get("/api/network-metrics/thresholds", params={"source": "web"})

    assert _original_fields(response.json()) == {
        "latency_warning_ms": 400,
        "latency_critical_ms": 800,
        "packet_loss_warning_percent": 1,
        "packet_loss_critical_percent": 5,
    }


def test_thresholds_for_native_match_the_call_without_source(client: TestClient) -> None:
    native = client.get("/api/network-metrics/thresholds", params={"source": "native"})

    assert native.json() == client.get("/api/network-metrics/thresholds").json()


def test_thresholds_with_an_unknown_source_are_rejected(client: TestClient) -> None:
    assert client.get("/api/network-metrics/thresholds", params={"source": "radio"}).status_code == 422


def test_a_web_measurement_of_250_ms_is_good(client: TestClient) -> None:
    response = client.post("/api/network-metrics", json={**SNAPSHOT_PAYLOAD, "latency_ms": 250, "source": "web"})

    assert response.json()["status"] == "good"


def test_a_measurement_without_source_is_still_judged_as_desktop(client: TestClient) -> None:
    # El instalador 0.1.5 no envía source: 250 ms sigue siendo crítico, como hoy.
    response = client.post("/api/network-metrics", json={**SNAPSHOT_PAYLOAD, "latency_ms": 250})

    assert response.json()["status"] == "critical"


def test_thresholds_without_token_is_unauthorized(client_without_claims_override: TestClient) -> None:
    response = client_without_claims_override.get("/api/network-metrics/thresholds")

    assert response.status_code == 401


def test_post_with_50_ms_and_3_percent_loss_is_a_warning(client: TestClient) -> None:
    response = client.post("/api/network-metrics", json={"latency_ms": 50, "jitter_ms": 2, "packet_loss_percent": 3})

    assert response.status_code == 201
    assert response.json()["status"] == "warning"


def test_history_includes_packet_loss_next_to_the_existing_fields(client: TestClient) -> None:
    client.post("/api/network-metrics", json={"latency_ms": 50, "jitter_ms": 2, "packet_loss_percent": 3})

    samples = client.get("/api/network-metrics/history").json()

    assert len(samples) == 1
    assert set(samples[0]) == {"timestamp", "latency_ms", "packet_loss_percent"}
    assert (samples[0]["latency_ms"], samples[0]["packet_loss_percent"]) == (50, 3)


def test_post_without_token_is_unauthorized(client_without_claims_override: TestClient) -> None:
    response = client_without_claims_override.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD)

    assert response.status_code == 401


def test_anomaly_status_is_calibrating_with_little_history(client: TestClient) -> None:
    payload = {**SNAPSHOT_PAYLOAD, "network_fingerprint": "b" * 64}
    client.post("/api/network-metrics", json=payload, headers={"Authorization": "Bearer fake"})

    response = client.get("/api/network-metrics/anomaly-status", headers={"Authorization": "Bearer fake"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "calibrating"
    assert body["samples_collected"] == 1
    assert body["samples_required"] > 1


def test_desktop_measurement_without_network_reports_unknown_network(client: TestClient) -> None:
    client.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD, headers={"Authorization": "Bearer fake"})

    body = client.get("/api/network-metrics/anomaly-status", headers={"Authorization": "Bearer fake"}).json()

    assert (body["status"], body["samples_collected"]) == ("unknown_network", 0)


def test_a_malformed_fingerprint_is_rejected(client: TestClient) -> None:
    payload = {**SNAPSHOT_PAYLOAD, "network_fingerprint": "3c-6a-d2-c8-5a-ec"}  # una MAC cruda no se acepta
    response = client.post("/api/network-metrics", json=payload, headers={"Authorization": "Bearer fake"})

    assert response.status_code == 422


if __name__ == "__main__":
    print("Run via pytest: python -m pytest tests/test_network_metrics_router.py")


def test_latest_says_which_source_measured_it(client: TestClient) -> None:
    client.post(
        "/api/network-metrics", json={**SNAPSHOT_PAYLOAD, "source": "web"}, headers={"Authorization": "Bearer fake"}
    )

    latest = client.get("/api/network-metrics/latest", headers={"Authorization": "Bearer fake"})

    assert latest.json()["source"] == "web"


def test_latest_without_measurements_has_no_source(client: TestClient) -> None:
    latest = client.get("/api/network-metrics/latest", headers={"Authorization": "Bearer fake"})

    assert latest.json()["source"] is None
