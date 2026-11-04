"""/api/realtime/ws con la app real, SQLite y el bus en memoria: Origin, autenticación por primer mensaje, cada código
de cierre y que cada usuario reciba solo lo suyo (y el admin, todo)."""

import contextlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.ai_gateway.shared_ai_status import AiStatusSnapshot
from app.core.ai_composition import _publish_ai_status
from app.core.config import get_settings
from app.core.database import get_db
from app.core.realtime_composition import get_realtime_authenticator, get_realtime_hub
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.device import Device
from app.models.role import Role
from app.models.user import User
from app.realtime.authenticator import RealtimeAuthenticator, RealtimeAuthError, RealtimeIdentity
from app.realtime.connections import CloseCode, ConnectionRegistry
from app.realtime.event_bus import InMemoryEventBus
from app.realtime.events import MEASUREMENT_CREATED, RealtimeEvent
from app.realtime.fanout import BatchedFanOut
from app.realtime.hub import RealtimeHub
from app.schemas.network_metrics import NetworkMetricSnapshotRead

ORIGIN = "https://web.test"
SOCKET_PATH = "/api/realtime/ws"
OWNER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
TOKEN_LIFETIME_SECONDS = 3600
SHORT_SECONDS = "0.3"
MAX_PER_USER = 5
MEASUREMENT = {"latency_ms": 20, "jitter_ms": 2, "packet_loss_percent": 0}


class _FakeAuthenticator(RealtimeAuthenticator):
    def __init__(self, identities: dict[str, RealtimeIdentity | RealtimeAuthError]) -> None:
        self._identities = identities

    def authenticate(self, token: str) -> RealtimeIdentity:
        identity = self._identities.get(token, RealtimeAuthError(CloseCode.UNAUTHORIZED))
        if isinstance(identity, RealtimeAuthError):
            raise identity
        return identity


def _identity(user_id: uuid.UUID, is_admin: bool = False, lifetime: float = TOKEN_LIFETIME_SECONDS) -> RealtimeIdentity:
    return RealtimeIdentity(user_id=user_id, is_admin=is_admin, expires_at=time.time() + lifetime)


class _Env:
    def __init__(self, client: TestClient, identities: dict, claims: dict, session_factory) -> None:
        self.client = client
        self.identities = identities
        self._claims = claims
        self.session_factory = session_factory

    def connect(self, origin: str | None = ORIGIN):
        headers = {"origin": origin} if origin else {}
        return self.client.websocket_connect(SOCKET_PATH, headers=headers)

    def act_as(self, user_id: uuid.UUID) -> None:
        self._claims.update({"sub": str(user_id), "email": f"{user_id}@example.com"})

    def post_measurement(self, user_id: uuid.UUID, **overrides) -> int:
        self.act_as(user_id)
        return self.client.post("/api/network-metrics", json={**MEASUREMENT, **overrides}).status_code


def _reset_cached_singletons() -> None:
    get_settings.cache_clear()
    get_realtime_hub.cache_clear()


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORS_ORIGINS", ORIGIN)
    monkeypatch.setenv("REALTIME_PING_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("REALTIME_MAX_CONNECTIONS_PER_USER", str(MAX_PER_USER))
    _reset_cached_singletons()
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

    claims: dict = {}
    identities: dict = {
        "owner": _identity(OWNER_ID),
        "other": _identity(OTHER_ID),
        "admin": _identity(ADMIN_ID, is_admin=True),
    }
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: dict(claims)
    app.dependency_overrides[get_realtime_authenticator] = lambda: _FakeAuthenticator(identities)
    try:
        with TestClient(app) as client:
            yield _Env(client, identities, claims, session_factory)
    finally:
        app.dependency_overrides.clear()
        _reset_cached_singletons()
        Base.metadata.drop_all(engine)


def _authenticate(socket, token: str) -> None:
    socket.send_json({"type": "auth", "token": token})
    assert socket.receive_json() == {"type": "ready", "server_id": get_realtime_hub().server_id}


def _close_code(socket) -> int:
    # Antes de cada cierre del servidor llega {"type": "close", "code": ...} con el mismo código que el frame.
    announced = socket.receive_json()
    with pytest.raises(WebSocketDisconnect) as closed:
        socket.receive_text()
    assert announced == {"type": "close", "code": closed.value.code}
    return closed.value.code


def _use_setting(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    get_settings.cache_clear()


@pytest.mark.parametrize("origin", ["https://evil.test", None])
def test_a_foreign_or_missing_origin_is_rejected_before_accepting(env: _Env, origin: str | None) -> None:
    with pytest.raises(WebSocketDisconnect) as rejected, env.connect(origin=origin):
        pass

    assert rejected.value.code == CloseCode.POLICY_VIOLATION


def test_without_the_auth_message_the_socket_closes_with_4408(env: _Env, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_setting(monkeypatch, "REALTIME_AUTH_TIMEOUT_SECONDS", SHORT_SECONDS)

    with env.connect() as socket:
        assert _close_code(socket) == CloseCode.AUTH_TIMEOUT


@pytest.mark.parametrize("first_message", [{"type": "auth", "token": "forged"}, {"type": "hello"}])
def test_an_invalid_token_or_another_first_message_closes_with_4401(env: _Env, first_message: dict) -> None:
    with env.connect() as socket:
        socket.send_json(first_message)
        assert _close_code(socket) == CloseCode.UNAUTHORIZED


def test_an_already_expired_token_closes_with_4401(env: _Env) -> None:
    env.identities["expired"] = _identity(OWNER_ID, lifetime=-1)

    with env.connect() as socket:
        socket.send_json({"type": "auth", "token": "expired"})
        assert _close_code(socket) == CloseCode.UNAUTHORIZED


def test_the_socket_closes_with_4401_when_the_token_expires(env: _Env) -> None:
    env.identities["short"] = _identity(OWNER_ID, lifetime=float(SHORT_SECONDS))

    with env.connect() as socket:
        _authenticate(socket, "short")
        assert _close_code(socket) == CloseCode.UNAUTHORIZED


def test_a_suspended_account_closes_with_4403(env: _Env) -> None:
    env.identities["suspended"] = RealtimeAuthError(CloseCode.FORBIDDEN)

    with env.connect() as socket:
        socket.send_json({"type": "auth", "token": "suspended"})
        assert _close_code(socket) == CloseCode.FORBIDDEN


def test_more_than_the_limit_of_sockets_per_user_closes_with_4429(env: _Env) -> None:
    with contextlib.ExitStack() as stack:
        for _ in range(MAX_PER_USER):
            _authenticate(stack.enter_context(env.connect()), "owner")
        extra = stack.enter_context(env.connect())
        extra.send_json({"type": "auth", "token": "owner"})
        assert _close_code(extra) == CloseCode.TOO_MANY_CONNECTIONS


def test_logging_out_closes_with_1000(env: _Env) -> None:
    with env.connect() as socket:
        _authenticate(socket, "owner")
        socket.send_json({"type": "logout"})
        assert _close_code(socket) == CloseCode.NORMAL


def test_renewing_the_token_with_another_user_closes_with_4401(env: _Env) -> None:
    with env.connect() as socket:
        _authenticate(socket, "owner")
        socket.send_json({"type": "auth", "token": "other"})
        assert _close_code(socket) == CloseCode.UNAUTHORIZED


def test_without_an_available_bus_the_socket_closes_with_1013(env: _Env) -> None:
    registry = ConnectionRegistry(MAX_PER_USER)
    unstarted = RealtimeHub(InMemoryEventBus(), registry, BatchedFanOut(registry, 1, 1), 1)
    app.dependency_overrides[get_realtime_hub] = lambda: unstarted

    with env.connect() as socket:
        assert _close_code(socket) == CloseCode.TRY_AGAIN_LATER


def test_an_idle_socket_receives_pings(env: _Env, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_setting(monkeypatch, "REALTIME_PING_INTERVAL_SECONDS", SHORT_SECONDS)

    with env.connect() as socket:
        _authenticate(socket, "owner")
        assert socket.receive_json() == {"type": "ping"}


def test_a_new_measurement_reaches_only_its_owner_and_the_admin(env: _Env) -> None:
    with env.connect() as owner, env.connect() as other, env.connect() as admin:
        _authenticate(owner, "owner")
        _authenticate(other, "other")
        _authenticate(admin, "admin")

        assert env.post_measurement(OTHER_ID, latency_ms=99) == 201
        assert env.post_measurement(OWNER_ID, latency_ms=20) == 201

        owner_event = owner.receive_json()
        assert (owner_event["type"], owner_event["owner_id"]) == ("measurement.created", str(OWNER_ID))
        assert owner_event["data"]["latency_ms"] == 20
        assert set(owner_event) == {"v", "type", "owner_id", "data", "at", "origin"}
        assert other.receive_json()["owner_id"] == str(OTHER_ID)
        assert [admin.receive_json()["owner_id"] for _ in range(2)] == [str(OTHER_ID), str(OWNER_ID)]


def test_an_ai_status_change_reaches_every_socket_of_every_user(env: _Env) -> None:
    with env.connect() as owner, env.connect() as other:
        _authenticate(owner, "owner")
        _authenticate(other, "other")

        _publish_ai_status(AiStatusSnapshot("unavailable", "timed_out"))

        for socket in (owner, other):
            event = socket.receive_json()
            assert (event["type"], event["owner_id"]) == ("ai.status.changed", None)
            assert event["data"] == {"status": "unavailable", "reason": "timed_out"}


def test_a_replayed_measurement_is_not_published_again(env: _Env) -> None:
    recorded_at = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()

    with env.connect() as owner:
        _authenticate(owner, "owner")
        env.post_measurement(OWNER_ID, latency_ms=20, recorded_at=recorded_at)
        env.post_measurement(OWNER_ID, latency_ms=20, recorded_at=recorded_at)
        env.post_measurement(OWNER_ID, latency_ms=30)

        assert [owner.receive_json()["data"]["latency_ms"] for _ in range(2)] == [20, 30]


def test_a_device_scan_publishes_devices_updated(env: _Env) -> None:
    with env.connect() as owner:
        _authenticate(owner, "owner")
        env.act_as(OWNER_ID)
        sync = {"devices": [{"mac_address": "aa-aa-aa-aa-aa-01", "ip_address": "192.168.1.10"}]}
        assert env.client.post("/api/devices/sync", json=sync).status_code == 200

        event = owner.receive_json()
        assert (event["type"], event["owner_id"], event["data"]) == ("devices.updated", str(OWNER_ID), {})


def test_a_failing_publish_never_breaks_the_measurement_post(env: _Env, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_publish(_event) -> None:
        raise ConnectionError("bus down")

    monkeypatch.setattr(get_realtime_hub()._bus, "publish", failing_publish)

    assert env.post_measurement(OWNER_ID) == 201
    env.act_as(OWNER_ID)
    assert env.client.get("/api/network-metrics/latest").json()["latency_ms"] == MEASUREMENT["latency_ms"]


CAMPUS_DEVICES = 1849
EVENT_SIZE_LIMIT_BYTES = 1024


def _add_users(env: _Env) -> None:
    with env.session_factory() as db:
        db.add_all(
            [
                User(id=OWNER_ID, email="owner@example.com", role_id=1),
                User(id=OTHER_ID, email="other@example.com", role_id=1),
                User(id=ADMIN_ID, email="admin@example.com", role_id=2),
            ]
        )
        db.commit()


def test_a_measurement_event_carries_only_the_measurement_even_with_1849_devices(env: _Env) -> None:
    _add_users(env)
    now = datetime.now(UTC)
    with env.session_factory() as db:
        db.add_all(
            Device(
                owner_id=OWNER_ID,
                name="",
                mac_address=f"aa-bb-cc-dd-{index >> 8:02x}-{index & 0xFF:02x}",
                ip_address=f"10.0.{index >> 8}.{index & 0xFF}",
                trust="unknown",
                network_role="other",
                first_seen=now,
                last_seen=now,
            )
            for index in range(CAMPUS_DEVICES)
        )
        db.commit()

    with env.connect() as owner:
        _authenticate(owner, "owner")
        assert env.post_measurement(OWNER_ID, source="native", gateway_latency_ms=150) == 201
        raw = owner.receive_text()

    data = json.loads(raw)["data"]
    assert set(data) == set(NetworkMetricSnapshotRead.model_fields)
    assert not [value for value in data.values() if isinstance(value, list | dict)]
    assert len(raw.encode()) < EVENT_SIZE_LIMIT_BYTES


def test_delivering_an_event_does_not_query_the_database(env: _Env) -> None:
    statements: list[str] = []

    def capture(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    with env.connect() as owner, env.connect() as admin:
        _authenticate(owner, "owner")
        _authenticate(admin, "admin")
        event.listen(Engine, "before_cursor_execute", capture)
        try:
            get_realtime_hub().publisher.publish(RealtimeEvent.now(MEASUREMENT_CREATED, OWNER_ID))
            assert owner.receive_json()["owner_id"] == str(OWNER_ID)
            assert admin.receive_json()["owner_id"] == str(OWNER_ID)
        finally:
            event.remove(Engine, "before_cursor_execute", capture)

    assert statements == []


def test_suspending_a_user_closes_their_sockets_and_the_reconnection_is_forbidden(env: _Env) -> None:
    _add_users(env)
    with env.connect() as owner, env.connect() as admin:
        _authenticate(owner, "owner")
        _authenticate(admin, "admin")
        env.act_as(ADMIN_ID)
        assert env.client.patch(f"/api/admin/users/{OWNER_ID}", json={"status": "suspended"}).status_code == 200

        assert _close_code(owner) == CloseCode.UNAUTHORIZED
        # El admin sigue conectado y recibiendo.
        assert env.post_measurement(OTHER_ID) == 201
        assert admin.receive_json()["owner_id"] == str(OTHER_ID)

    env.identities["owner"] = RealtimeAuthError(CloseCode.FORBIDDEN)
    with env.connect() as again:
        again.send_json({"type": "auth", "token": "owner"})
        assert _close_code(again) == CloseCode.FORBIDDEN


def test_a_demoted_admin_stops_receiving_other_users_events(env: _Env) -> None:
    _add_users(env)
    with env.connect() as admin:
        _authenticate(admin, "admin")
        env.act_as(ADMIN_ID)
        # Otro admin le quita el rol: el socket se cierra y al volver solo recibe lo suyo.
        other_admin = uuid.uuid4()
        with env.session_factory() as db:
            db.add(User(id=other_admin, email="second-admin@example.com", role_id=2))
            db.commit()
        env.act_as(other_admin)
        assert env.client.patch(f"/api/admin/users/{ADMIN_ID}", json={"role": "standard"}).status_code == 200
        assert _close_code(admin) == CloseCode.UNAUTHORIZED

    env.identities["admin"] = _identity(ADMIN_ID, is_admin=False)
    with env.connect() as demoted:
        _authenticate(demoted, "admin")
        assert env.post_measurement(OTHER_ID) == 201
        assert env.post_measurement(ADMIN_ID) == 201
        assert demoted.receive_json()["owner_id"] == str(ADMIN_ID)


def test_editing_only_the_name_keeps_the_sockets_open(env: _Env) -> None:
    _add_users(env)
    with env.connect() as owner:
        _authenticate(owner, "owner")
        env.act_as(ADMIN_ID)
        assert env.client.patch(f"/api/admin/users/{OWNER_ID}", json={"full_name": "Nuevo nombre"}).status_code == 200
        assert env.post_measurement(OWNER_ID) == 201
        assert owner.receive_json()["type"] == "measurement.created"


def test_deleting_a_user_closes_their_sockets(env: _Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.routers.admin_users.SupabaseAdminClient", _FakeSupabaseAdminClient)
    _add_users(env)
    with env.connect() as owner:
        _authenticate(owner, "owner")
        env.act_as(ADMIN_ID)
        assert env.client.delete(f"/api/admin/users/{OWNER_ID}").status_code == 204
        assert _close_code(owner) == CloseCode.UNAUTHORIZED


class _FakeSupabaseAdminClient:
    def __init__(self, _settings) -> None:
        pass

    def delete_user(self, _user_id: uuid.UUID) -> None:
        pass
