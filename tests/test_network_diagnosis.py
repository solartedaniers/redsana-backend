"""Diagnóstico router / proveedor y pista de dispositivo saturando: la regla sola y por la API con SQLite, incluido
que el instalador 0.1.5 y la web (sin latencia al router) siguen igual. La tabla de paridad es la misma que prueba el
escritorio, que replica la regla para diagnosticar sin conexión."""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_claims
from app.domain.network_diagnosis import NetworkDiagnosisPolicy
from app.domain.network_status import NetworkStatusThresholds, compute_network_status
from app.main import app
from app.models.base import Base
from app.models.device import Device
from app.models.role import Role
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.services.network_diagnosis_service import NetworkDiagnosisService

POLICY = NetworkDiagnosisPolicy(
    gateway_latency_bad_ms=100, busy_device_min_count=8, gateway_recent_reply_window=timedelta(minutes=60)
)
BACKEND_DIR = Path(__file__).resolve().parents[1]
PARITY_FILE = BACKEND_DIR / "tests" / "fixtures" / "network_diagnosis_cases.json"
# La misma huella está en la prueba del frontend: si alguien cambia una copia y no la otra, falla una de las dos.
PARITY_SHA256 = "5766dc764583233a63b2e50f5d8932313cd40299dac2ea07eb1e5992677fe584"
FRONTEND_PARITY_PATH = Path("src/app/core/domain/network-diagnosis-cases.json")
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


def _parity_bytes(path: Path) -> bytes:
    # Sin \r: git puede dejar el archivo con CRLF en Windows.
    return path.read_bytes().replace(b"\r", b"")


PARITY = json.loads(_parity_bytes(PARITY_FILE))


def test_the_parity_table_is_the_agreed_one() -> None:
    assert hashlib.sha256(_parity_bytes(PARITY_FILE)).hexdigest() == PARITY_SHA256


@pytest.mark.parametrize("case", PARITY["cases"], ids=[case["name"] for case in PARITY["cases"]])
def test_the_rule_matches_the_parity_table(case: dict) -> None:
    limits = PARITY["thresholds"]
    policy = NetworkDiagnosisPolicy(
        gateway_latency_bad_ms=limits["gateway_latency_bad_ms"],
        busy_device_min_count=8,
        gateway_recent_reply_window=timedelta(minutes=limits["gateway_recent_reply_minutes"]),
    )
    status = compute_network_status(
        case["latency_ms"],
        case["packet_loss_percent"],
        NetworkStatusThresholds(
            latency_warning_ms=limits["latency_warning_ms"],
            latency_critical_ms=limits["latency_critical_ms"],
            packet_loss_warning_percent=limits["packet_loss_warning_percent"],
            packet_loss_critical_percent=limits["packet_loss_critical_percent"],
        ),
    )
    measured_at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    minutes = case["minutes_since_router_reply"]
    last_reply = None if minutes is None else measured_at - timedelta(minutes=minutes)

    diagnosis = policy.diagnose(
        status,
        case["gateway_latency_ms"],
        packet_loss_percent=case["packet_loss_percent"],
        router_replied_recently=policy.router_replied_recently(last_reply, measured_at),
    )

    assert diagnosis == case["expected"]


def test_the_frontend_has_the_same_parity_table() -> None:
    """Con el repo del frontend al lado (FRONTEND_I18N_DIR, como la prueba de claves de alertas) compara las copias."""
    raw = os.environ.get("FRONTEND_I18N_DIR") or dotenv_values(BACKEND_DIR / ".env").get("FRONTEND_I18N_DIR")
    if not raw:
        pytest.skip("FRONTEND_I18N_DIR no está definida: la huella SHA-256 sigue protegiendo la tabla")
    frontend_copy = (BACKEND_DIR / raw).resolve().parents[2] / FRONTEND_PARITY_PATH
    assert _parity_bytes(frontend_copy) == _parity_bytes(PARITY_FILE)


@pytest.mark.parametrize(
    ("gateway", "devices", "expected"),
    [(150, 8, True), (150, 7, False), (20, 12, False), (None, 12, None)],
)
def test_the_busy_device_hint(gateway: float | None, devices: int, expected: bool | None) -> None:
    assert POLICY.possible_busy_device(gateway, devices) is expected


def test_the_thresholds_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_GATEWAY_LATENCY_BAD_MS", "30")
    monkeypatch.setenv("NETWORK_BUSY_DEVICE_MIN_COUNT", "3")
    monkeypatch.setenv("NETWORK_GATEWAY_RECENT_REPLY_MINUTES", "15")
    get_settings.cache_clear()
    try:
        policy = get_settings().network_diagnosis_policy
    finally:
        get_settings.cache_clear()

    assert (policy.gateway_latency_bad_ms, policy.busy_device_min_count) == (30, 3)
    assert policy.gateway_recent_reply_window == timedelta(minutes=15)


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


def _post_at(client: TestClient, minutes_ago: float, **fields) -> None:
    # Como la cola del escritorio: medida hace un rato y enviada ahora (el backend corrige el reloj con sent_at).
    now = datetime.now(UTC)
    timing = {"recorded_at": (now - timedelta(minutes=minutes_ago)).isoformat(), "sent_at": now.isoformat()}
    response = client.post("/api/network-metrics", json={**NATIVE, **fields, **timing})
    assert response.status_code == 201, response.text


INTERNET_DOWN = {"latency_ms": 0, "packet_loss_percent": 100}


def test_internet_down_and_a_router_that_answered_recently_points_to_wifi_or_router(env) -> None:
    client, _ = env
    _post_at(client, 10, gateway_latency_ms=4)
    _post_at(client, 0, **INTERNET_DOWN)

    latest = _latest(client)

    assert (latest["diagnosis"], latest["possible_busy_device"]) == ("router_unreachable", None)


def test_a_router_that_answered_too_long_ago_is_not_blamed(env) -> None:
    client, _ = env
    _post_at(client, 61, gateway_latency_ms=4)
    _post_at(client, 0, **INTERNET_DOWN)

    assert _latest(client)["diagnosis"] is None


def test_a_router_that_never_answers_the_ping_is_not_blamed(env) -> None:
    client, _ = env
    _post_at(client, 5)
    _post_at(client, 0, **INTERNET_DOWN)

    assert _latest(client)["diagnosis"] is None


def test_only_router_replies_up_to_the_measurement_count(env) -> None:
    """Una medición vieja que llega tarde de la cola se juzga en su momento, no con respuestas posteriores."""
    client, session_factory = env
    _post_at(client, 30, **INTERNET_DOWN)
    _post_at(client, 0, gateway_latency_ms=4)

    with session_factory() as db:
        repository = SqlAlchemyNetworkMetricsRepository(db)
        old = repository.list_latest(OWNER_ID, limit=2)[-1]
        service = NetworkDiagnosisService(SqlAlchemyDeviceRepository(db), repository, POLICY)

        assert service.describe(OWNER_ID, old).diagnosis is None


def test_the_web_never_blames_the_router_even_if_the_desktop_measured_it(env) -> None:
    client, _ = env
    _post_at(client, 5, gateway_latency_ms=4)
    client.post("/api/network-metrics", json={"jitter_ms": 2, **INTERNET_DOWN, "source": "web"})

    assert _latest(client)["diagnosis"] is None


def test_the_installer_0_1_5_with_internet_down_is_not_diagnosed(env) -> None:
    client, _ = env
    client.post("/api/network-metrics", json={"jitter_ms": 2, **INTERNET_DOWN})

    assert _latest(client)["diagnosis"] is None


def test_the_thresholds_include_the_router_rule_for_the_desktop(env) -> None:
    client, _ = env

    body = client.get("/api/network-metrics/thresholds", params={"source": "native"}).json()

    assert body == {
        "latency_warning_ms": 80,
        "latency_critical_ms": 150,
        "packet_loss_warning_percent": 1,
        "packet_loss_critical_percent": 5,
        "gateway_latency_bad_ms": 100,
        "gateway_recent_reply_minutes": 60,
    }


def test_a_negative_router_latency_is_rejected(env) -> None:
    client, _ = env

    assert client.post("/api/network-metrics", json={**NATIVE, "gateway_latency_ms": -1}).status_code == 422
