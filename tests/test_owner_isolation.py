"""A nivel de router y con SQLite: el usuario B no ve ni cambia nada del usuario A, un usuario estándar no entra a ninguna
ruta de admin y una cuenta suspendida recibe 403 en todo lo que lleva sus datos."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.ai_composition import get_ai_gateway, get_chat_engine
from app.core.authorization import reject_suspended
from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.role import Role
from app.models.user import User
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.routers import admin_households, admin_metrics, admin_users
from tests.test_chat_conversations_router import _StubGroqClient
from tests.test_security_assessment_router import ANSWERS_PAYLOAD

USER_A = {"sub": str(uuid.uuid4()), "email": "a@example.com"}
USER_B = {"sub": str(uuid.uuid4()), "email": "b@example.com"}
CHAT_PREFIXES = ["/api/chat-conversations", "/api/conversations"]


class World:
    """App con SQLite y un usuario activo que se cambia con `as_user`; A ya tiene un dato de cada tipo."""

    def __init__(self) -> None:
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        with self.sessions() as db:
            db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
            db.commit()
        self.claims = USER_A
        self.model = _StubGroqClient(reply="respuesta")

        def override_get_db():
            db = self.sessions()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_claims] = lambda: self.claims
        app.dependency_overrides[get_chat_engine] = lambda: self.model
        self.client = TestClient(app)

    def as_user(self, claims: dict) -> TestClient:
        self.claims = claims
        return self.client

    def set_user(self, claims: dict, **values) -> None:
        with self.sessions() as db:
            db.execute(update(User).where(User.id == uuid.UUID(claims["sub"])).values(**values))
            db.commit()

    def seed_user_a(self) -> SimpleNamespace:
        client = self.as_user(USER_A)
        device = client.post("/api/devices", json={"name": "Portátil", "mac_address": "aa-bb-cc-dd-ee-01", "ip_address": "192.168.1.20"})
        conversation = client.post("/api/chat-conversations", json={})
        assessment = client.post("/api/security-assessments", json=ANSWERS_PAYLOAD)
        assert (device.status_code, conversation.status_code, assessment.status_code) == (201, 201, 201)
        with self.sessions() as db:
            alert = SqlAlchemyAlertRepository(db).create(
                uuid.UUID(USER_A["sub"]), "outage", "critical", "user.alertsCenter.messages.briefOutage", None, None
            )
            alert_id = str(alert.id)
        client.get("/api/users/me")
        self.as_user(USER_B).get("/api/users/me")
        return SimpleNamespace(
            device=device.json()["id"],
            conversation=conversation.json()["id"],
            assessment=assessment.json()["id"],
            alert=alert_id,
        )


@pytest.fixture()
def world():
    created = World()
    try:
        yield created
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(created.engine)


# --- B contra A -------------------------------------------------------------------------------------------------------


def test_b_cannot_change_a_device_of_a(world: World) -> None:
    a = world.seed_user_a()

    response = world.as_user(USER_B).patch(f"/api/devices/{a.device}", json={"trust": "blocked", "name": "mío"})

    assert response.status_code == 404
    device = world.as_user(USER_A).get("/api/devices").json()[0]
    assert (device["trust"], device["name"]) == ("unknown", "Portátil")
    assert world.as_user(USER_B).get("/api/devices").json() == []


def test_b_cannot_acknowledge_an_alert_of_a(world: World) -> None:
    a = world.seed_user_a()

    response = world.as_user(USER_B).patch(f"/api/alerts/{a.alert}/acknowledge")

    assert response.status_code == 404
    assert [alert["acknowledged"] for alert in world.as_user(USER_A).get("/api/alerts").json()] == [False]
    assert world.as_user(USER_B).get("/api/alerts").json() == []


@pytest.mark.parametrize("prefix", CHAT_PREFIXES)
def test_b_cannot_rename_a_conversation_of_a(world: World, prefix: str) -> None:
    a = world.seed_user_a()

    response = world.as_user(USER_B).patch(f"{prefix}/{a.conversation}", json={"title": "de B"})

    assert response.status_code == 404
    assert [c["title"] for c in world.as_user(USER_A).get("/api/chat-conversations").json()] != ["de B"]
    assert world.as_user(USER_B).get("/api/chat-conversations").json() == []


@pytest.mark.parametrize("prefix", CHAT_PREFIXES)
def test_b_cannot_read_or_post_messages_in_a_conversation_of_a(world: World, prefix: str) -> None:
    a = world.seed_user_a()
    client = world.as_user(USER_B)

    assert client.get(f"{prefix}/{a.conversation}/messages").status_code == 404
    assert client.post(f"{prefix}/{a.conversation}/messages", json={"message": "hola"}).status_code == 404
    assert world.model.calls == []
    assert world.as_user(USER_A).get(f"/api/chat-conversations/{a.conversation}/messages").json() == []


def test_b_cannot_open_a_briefing_of_the_assessment_of_a(world: World) -> None:
    a = world.seed_user_a()

    response = world.as_user(USER_B).post(
        "/api/chat-conversations/briefings", json={"assessment_id": a.assessment, "language": "es"}
    )

    assert response.status_code == 404
    assert world.model.calls == []
    assert world.as_user(USER_B).get("/api/chat-conversations").json() == []


@pytest.mark.parametrize("path", ["latest", "history", "anomaly-status"])
def test_a_standard_b_cannot_read_the_network_of_a(world: World, path: str) -> None:
    world.seed_user_a()

    response = world.as_user(USER_B).get(f"/api/network-metrics/{path}", params={"user_id": USER_A["sub"]})

    assert response.status_code == 403


# --- Rutas de admin -----------------------------------------------------------------------------------------------------


# (router, prefijos con que main.py lo monta): admin_metrics no tiene prefijo propio y va con el nombre nuevo y el alias.
ADMIN_ROUTERS = [
    (admin_users.router, [""]),
    (admin_households.router, [""]),
    (admin_metrics.router, [admin_metrics.PLATFORM_METRICS_PREFIX, admin_metrics.LEGACY_PLATFORM_METRICS_PREFIX]),
]


def _admin_routes() -> list[tuple[str, str]]:
    """Cada ruta de admin con cada método, también los alias ocultos de /docs."""
    return [
        (method, prefix + route.path)
        for router, prefixes in ADMIN_ROUTERS
        for prefix in prefixes
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods)
    ]


def test_the_admin_route_list_covers_every_documented_admin_route() -> None:
    """Si se agrega un router de admin, esta prueba avisa que falta en ADMIN_ROUTERS."""
    documented = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/admin")
        for method in operations
    }

    assert documented <= set(_admin_routes())


@pytest.mark.parametrize(("method", "path"), _admin_routes())
def test_a_standard_user_gets_403_on_every_admin_route(world: World, method: str, path: str) -> None:
    client = world.as_user(USER_B)
    url = path.replace("{user_id}", str(uuid.uuid4())).replace("{household_id}", str(uuid.uuid4()))

    response = client.request(method, url, json={} if method in {"POST", "PATCH", "PUT"} else None)

    assert response.status_code == 403, url


# --- Cuenta suspendida ------------------------------------------------------------------------------------------------

SUSPENDED_READS = [
    "/api/users/me",
    "/api/me",
    "/api/devices",
    "/api/alerts",
    "/api/alerts/recent?since=2026-01-01T00:00:00Z",
    "/api/chat-conversations",
    "/api/conversations",
    "/api/network-metrics/latest",
    "/api/network-metrics/thresholds",
    "/api/security-assessments/latest",
]


@pytest.mark.parametrize("path", SUSPENDED_READS)
def test_a_suspended_account_gets_403_on_its_data(world: World, path: str) -> None:
    world.seed_user_a()
    world.set_user(USER_A, is_active=False)

    response = world.as_user(USER_A).get(path)

    assert response.status_code == 403
    assert response.json() == {"detail": "Account suspended"}


def test_a_suspended_account_cannot_write_either(world: World) -> None:
    a = world.seed_user_a()
    world.set_user(USER_A, is_active=False)
    client = world.as_user(USER_A)

    assert client.patch("/api/users/me", json={"full_name": "otro"}).status_code == 403
    assert client.patch(f"/api/devices/{a.device}", json={"trust": "trusted"}).status_code == 403
    assert client.post(f"/api/chat-conversations/{a.conversation}/messages", json={"message": "hola"}).status_code == 403
    assert world.model.calls == []


def test_a_suspended_admin_loses_the_admin_routes(world: World) -> None:
    world.seed_user_a()
    world.set_user(USER_A, role_id=2)
    assert world.as_user(USER_A).get("/api/admin/users").status_code == 200

    world.set_user(USER_A, is_active=False)

    assert world.as_user(USER_A).get("/api/admin/users").status_code == 403


def test_the_ai_status_stays_open_for_a_suspended_account(world: World) -> None:
    """Decisión: /api/ai/status y /api/ai/warm-up no usan la base a propósito y no exponen datos del usuario."""
    world.seed_user_a()
    world.set_user(USER_A, is_active=False)
    app.dependency_overrides[get_ai_gateway] = lambda: SimpleNamespace(
        status=lambda: "ready", unavailable_reason=lambda: None, start_warm_up=lambda: None
    )

    assert world.as_user(USER_A).get("/api/ai/status").status_code == 200


def test_reactivating_the_account_gives_access_back(world: World) -> None:
    world.seed_user_a()
    world.set_user(USER_A, is_active=False)
    world.set_user(USER_A, is_active=True)

    assert world.as_user(USER_A).get("/api/users/me").status_code == 200


@pytest.mark.parametrize("value", [True, None])
def test_only_an_explicit_false_suspends(value) -> None:
    user = SimpleNamespace(is_active=value)

    assert reject_suspended(user) is user


def test_an_explicit_false_is_rejected_with_403() -> None:
    with pytest.raises(HTTPException) as error:
        reject_suspended(SimpleNamespace(is_active=False))

    assert error.value.status_code == 403
