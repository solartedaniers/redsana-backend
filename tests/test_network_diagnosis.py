"""Diagnóstico router / proveedor y pista de dispositivo saturando: la regla sola y por la API con SQLite, incluido
que el instalador 0.1.5 y la web (sin latencia al router) siguen igual."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_claims
from app.domain.network_diagnosis import NetworkDiagnosisPolicy
from app.main import app
from app.models.base import Base
from app.models.device import Device
from app.models.role import Role

POLICY = NetworkDiagnosisPolicy(gateway_latency_bad_ms=100, busy_device_min_count=8)
OWNER_ID = uuid.uuid4()


@pytest.mark.parametrize(
    ("status", "gateway", "expected"),
    [
        ("critical", 150, "router"),
        ("good", 100, "router"),
        ("critical", 5, "provider"),
        ("warning", 99, "provider"),
        ("good", 5, "ok"),
        ("critical", None, None),
        ("good", None, None),
    ],
)
def test_the_rule(status: str, gateway: float | None, expected: str | None) -> None:
    assert POLICY.diagnose(status, gateway) == expected


@pytest.mark.parametrize(
    ("gateway", "devices", "expected"),
    [(150, 8, True), (150, 7, False), (20, 12, False), (None, 12, None)],
)
def test_the_busy_device_hint(gateway: float | None, devices: int, expected: bool | None) -> None:
    assert POLICY.possible_busy_device(gateway, devices) is expected


def test_the_thresholds_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_GATEWAY_LATENCY_BAD_MS", "30")
    monkeypatch.setenv("NETWORK_BUSY_DEVICE_MIN_COUNT", "3")
    get_settings.cache_clear()
    try:
        policy = get_settings().network_diagnosis_policy
    finally:
        get_settings.cache_clear()

    assert (policy.gateway_latency_bad_ms, policy.busy_device_min_count) == (30, 3)


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
        db.commit()
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
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _seed_connected_devices(client: TestClient, session_factory, count: int) -> None:
    client.get("/api/network-metrics/latest")  # crea el usuario en su primer request
    now = datetime.now(UTC)
    with session_factory() as db:
        db.add_all(
            Device(
                owner_id=OWNER_ID,
                name="",
                mac_address=f"aa-bb-cc-dd-ee-{i:02x}",
                ip_address=f"192.168.1.{i + 10}",
                trust="unknown",
                network_role="other",
                first_seen=now - timedelta(minutes=5),
                last_seen=now,
            )
            for i in range(count)
        )
        db.commit()


def _latest(client: TestClient) -> dict:
    return client.get("/api/network-metrics/latest").json()


NATIVE = {"latency_ms": 20, "jitter_ms": 2, "packet_loss_percent": 0, "source": "native"}


def test_router_bad_is_a_wifi_or_router_problem(env) -> None:
    client, _ = env
    client.post("/api/network-metrics", json={**NATIVE, "latency_ms": 300, "gateway_latency_ms": 180})

    latest = _latest(client)

    assert (latest["gateway_latency_ms"], latest["diagnosis"]) == (180, "router")


def test_router_fine_and_internet_bad_is_the_provider(env) -> None:
    client, _ = env
    client.post("/api/network-metrics", json={**NATIVE, "latency_ms": 300, "gateway_latency_ms": 4})

    assert _latest(client)["diagnosis"] == "provider"


def test_everything_fine_is_no_problem(env) -> None:
    client, _ = env
    client.post("/api/network-metrics", json={**NATIVE, "gateway_latency_ms": 4})

    assert _latest(client)["diagnosis"] == "ok"


def test_many_devices_and_a_slow_router_suggest_a_busy_device_as_possible(env) -> None:
    client, session_factory = env
    _seed_connected_devices(client, session_factory, 8)
    client.post("/api/network-metrics", json={**NATIVE, "gateway_latency_ms": 180})

    assert _latest(client)["possible_busy_device"] is True


def test_few_devices_do_not_suggest_a_busy_device(env) -> None:
    client, session_factory = env
    _seed_connected_devices(client, session_factory, 2)
    client.post("/api/network-metrics", json={**NATIVE, "gateway_latency_ms": 180})

    assert _latest(client)["possible_busy_device"] is False


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"latency_ms": 900, "jitter_ms": 2, "packet_loss_percent": 0}, id="instalador-0.1.5"),
        pytest.param({"latency_ms": 900, "jitter_ms": 2, "packet_loss_percent": 0, "source": "web"}, id="web-actual"),
    ],
)
def test_without_router_latency_nothing_changes_and_nothing_is_diagnosed(env, payload: dict) -> None:
    client, _ = env

    created = client.post("/api/network-metrics", json=payload)
    latest = _latest(client)

    assert created.status_code == 201
    assert latest["status"] in {"warning", "critical"}
    assert (latest["gateway_latency_ms"], latest["diagnosis"], latest["possible_busy_device"]) == (None, None, None)


def test_a_negative_router_latency_is_rejected(env) -> None:
    client, _ = env

    assert client.post("/api/network-metrics", json={**NATIVE, "gateway_latency_ms": -1}).status_code == 422
