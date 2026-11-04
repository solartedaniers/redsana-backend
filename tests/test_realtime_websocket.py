"""/api/realtime/ws con la app real, SQLite y el bus en memoria: Origin, autenticación por primer mensaje, cada código
de cierre y que cada usuario reciba solo lo suyo (y el admin, todo)."""

import contextlib
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.database import get_db
from app.core.realtime_composition import get_realtime_authenticator, get_realtime_hub
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.role import Role
from app.realtime.authenticator import RealtimeAuthenticator, RealtimeAuthError, RealtimeIdentity
from app.realtime.connections import CloseCode, ConnectionRegistry
from app.realtime.event_bus import InMemoryEventBus
from app.realtime.fanout import BatchedFanOut
from app.realtime.hub import RealtimeHub

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
    def __init__(self, client: TestClient, identities: dict, claims: dict) -> None:
        self.client = client
        self.identities = identities
        self._claims = claims

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
            yield _Env(client, identities, claims)
    finally:
        app.dependency_overrides.clear()
        _reset_cached_singletons()
        Base.metadata.drop_all(engine)


def _authenticate(socket, token: str) -> None:
    socket.send_json({"type": "auth", "token": token})
    assert socket.receive_json() == {"type": "ready"}


def _close_code(socket) -> int:
    with pytest.raises(WebSocketDisconnect) as closed:
        socket.receive_text()
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
