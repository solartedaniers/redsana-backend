"""Los endpoints cacheados responden lo mismo que sin caché, se invalidan con cada escritura y siguen sin Redis."""

import uuid

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache.cache_store import FailureCooldown, NullCacheStore, RedisCacheStore
from app.cache.owner_cache import OwnerCache
from app.core.cache_composition import get_owner_cache
from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.role import Role
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository

OWNER_USER_ID = uuid.uuid4()
SNAPSHOT_PAYLOAD = {"latency_ms": 20, "jitter_ms": 2, "packet_loss_percent": 0}
HOME_NETWORK_FINGERPRINT = "b" * 64
SYNC_PAYLOAD = {"devices": [{"mac_address": "aa-aa-aa-aa-aa-01", "ip_address": "192.168.1.10"}]}


class _App:
    def __init__(self, client: TestClient, session_factory, redis_server: fakeredis.FakeServer) -> None:
        self.client = client
        self.session_factory = session_factory
        self.redis_server = redis_server

    def use_cache(self, cache: OwnerCache) -> None:
        app.dependency_overrides[get_owner_cache] = lambda: cache

    def write_snapshot_behind_the_api(self, latency_ms: float) -> None:
        """Escribe sin pasar por el router, así que nada invalida la caché: sirve para saber de dónde se leyó."""
        with self.session_factory() as db:
            SqlAlchemyNetworkMetricsRepository(db).create(
                owner_id=OWNER_USER_ID,
                latency_ms=latency_ms,
                jitter_ms=1,
                packet_loss_percent=0,
                status="good",
                source="native",
                recorded_at=None,
            )


@pytest.fixture()
def setup(monkeypatch: pytest.MonkeyPatch):
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

    redis_server = fakeredis.FakeServer()
    redis_client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    cache = OwnerCache(RedisCacheStore(redis_client, FailureCooldown(0)), "test")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: {"sub": str(OWNER_USER_ID), "email": "owner@example.com"}
    app.dependency_overrides[get_owner_cache] = lambda: cache
    try:
        yield _App(TestClient(app), session_factory, redis_server)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_latest_answers_the_same_json_with_and_without_the_cache(setup: _App) -> None:
    setup.client.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD)
    setup.client.post("/api/devices/sync", json=SYNC_PAYLOAD)
    paths = ["/api/network-metrics/latest", "/api/network-metrics/anomaly-status", "/api/devices"]

    cold = [setup.client.get(path).json() for path in paths]
    cached = [setup.client.get(path).json() for path in paths]
    setup.use_cache(OwnerCache(NullCacheStore(), "test"))
    without_cache = [setup.client.get(path).json() for path in paths]

    assert cold == cached == without_cache


def test_a_new_measurement_invalidates_latest_and_anomaly_status(setup: _App) -> None:
    home_measurement = {**SNAPSHOT_PAYLOAD, "network_fingerprint": HOME_NETWORK_FINGERPRINT}
    setup.client.post("/api/network-metrics", json=home_measurement)
    setup.client.get("/api/network-metrics/latest")
    before = setup.client.get("/api/network-metrics/anomaly-status").json()
    setup.write_snapshot_behind_the_api(latency_ms=99)

    assert setup.client.get("/api/network-metrics/latest").json()["latency_ms"] == SNAPSHOT_PAYLOAD["latency_ms"]
    assert setup.client.get("/api/network-metrics/anomaly-status").json() == before

    setup.client.post("/api/network-metrics", json={**home_measurement, "latency_ms": 30})

    assert setup.client.get("/api/network-metrics/latest").json()["latency_ms"] == 30
    after = setup.client.get("/api/network-metrics/anomaly-status").json()
    assert before["samples_collected"] == 1
    assert after["samples_collected"] == 2


def test_without_measurements_the_default_answer_is_not_cached(setup: _App) -> None:
    assert setup.client.get("/api/network-metrics/latest").json()["status"] == "unknown"

    setup.write_snapshot_behind_the_api(latency_ms=42)

    assert setup.client.get("/api/network-metrics/latest").json()["latency_ms"] == 42


def test_a_device_scan_invalidates_the_device_list(setup: _App) -> None:
    assert setup.client.get("/api/devices").json() == []

    setup.client.post("/api/devices/sync", json=SYNC_PAYLOAD)

    assert [device["mac_address"] for device in setup.client.get("/api/devices").json()] == ["aa-aa-aa-aa-aa-01"]


def test_with_redis_down_the_endpoints_read_from_the_database(setup: _App) -> None:
    setup.redis_server.connected = False

    assert setup.client.post("/api/network-metrics", json=SNAPSHOT_PAYLOAD).status_code == 201
    assert setup.client.get("/api/network-metrics/latest").json()["latency_ms"] == SNAPSHOT_PAYLOAD["latency_ms"]
    assert setup.client.post("/api/devices/sync", json=SYNC_PAYLOAD).status_code == 200
    assert len(setup.client.get("/api/devices").json()) == 1


def test_the_cached_endpoints_keep_the_response_schema_the_clients_read() -> None:
    """La web y los instaladores 0.1.5 a 0.1.8 leen estos esquemas: la caché no puede volverlos opcionales."""
    paths = app.openapi()["paths"]

    def schema(path: str) -> dict:
        return paths[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]

    assert schema("/api/network-metrics/latest") == {"$ref": "#/components/schemas/NetworkMetricSnapshotRead"}
    assert schema("/api/network-metrics/anomaly-status") == {"$ref": "#/components/schemas/AnomalyStatusRead"}
    assert schema("/api/devices")["type"] == "array"
    assert schema("/api/devices")["items"] == {"$ref": "#/components/schemas/DeviceRead"}
