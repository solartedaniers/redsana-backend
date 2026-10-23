"""Rutas renombradas: el nombre nuevo y el anterior (alias oculto para el instalador 0.1.5 y la web desplegada)
responden lo mismo, piden la misma autenticación y aceptan el preflight CORS; solo el nuevo sale en /docs."""
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.authorization import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.role import Role

CLAIMS = {"sub": str(uuid.uuid4()), "email": "owner@example.com"}
# Con "Z" y no "+00:00": en una query string el "+" llega como espacio.
SINCE = "2026-01-01T00:00:00Z"

# (método, ruta nueva, ruta anterior)
RENAMED_ROUTES = [
    ("GET", "/api/users/me", "/api/me"),
    ("PATCH", "/api/users/me", "/api/me"),
    ("GET", "/api/chat-conversations", "/api/conversations"),
    ("POST", "/api/chat-conversations", "/api/conversations"),
    ("PATCH", "/api/chat-conversations/{conversation_id}", "/api/conversations/{conversation_id}"),
    ("GET", "/api/chat-conversations/{conversation_id}/messages", "/api/conversations/{conversation_id}/messages"),
    ("POST", "/api/chat-conversations/{conversation_id}/messages", "/api/conversations/{conversation_id}/messages"),
    ("POST", "/api/chat-conversations/briefings", "/api/conversations/briefings"),
    ("GET", "/api/alerts/recent", "/api/alerts/new"),
    ("GET", "/api/admin/platform-metrics", "/api/admin/metrics"),
]

# Lecturas sin efectos que se pueden comparar tal cual.
READS = [
    ("/api/users/me", "/api/me"),
    ("/api/chat-conversations", "/api/conversations"),
    (f"/api/alerts/recent?since={SINCE}", f"/api/alerts/new?since={SINCE}"),
    ("/api/admin/platform-metrics", "/api/admin/metrics"),
]


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
        db.commit()
    return engine, factory


def _override_db(factory):
    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    return override_get_db


@pytest.fixture()
def client():
    engine, factory = _session_factory()
    app.dependency_overrides[get_db] = _override_db(factory)
    app.dependency_overrides[get_current_claims] = lambda: CLAIMS
    # Las métricas de la plataforma son solo para admin; aquí importa la ruta, no el rol.
    app.dependency_overrides[require_admin] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client_without_token():
    engine, factory = _session_factory()
    app.dependency_overrides[get_db] = _override_db(factory)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_only_the_new_names_are_documented() -> None:
    paths = app.openapi()["paths"]

    for method, new, old in RENAMED_ROUTES:
        assert method.lower() in paths.get(new, {}), new
        assert old not in paths, old


@pytest.mark.parametrize(("new", "old"), READS)
def test_old_and_new_names_answer_the_same(client: TestClient, new: str, old: str) -> None:
    client.post("/api/chat-conversations", json={})
    new_response = client.get(new)
    old_response = client.get(old)

    assert new_response.status_code == 200
    assert (old_response.status_code, old_response.json()) == (new_response.status_code, new_response.json())


def test_a_conversation_created_with_the_old_name_is_read_with_the_new_one(client: TestClient) -> None:
    created = client.post("/api/conversations", json={})

    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert client.get(f"/api/chat-conversations/{conversation_id}/messages").status_code == 200
    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "Nueva"})
    assert renamed.status_code == 200
    assert [c["title"] for c in client.get("/api/chat-conversations").json()] == ["Nueva"]


@pytest.mark.parametrize(("new", "old"), READS)
def test_both_names_require_a_token(client_without_token: TestClient, new: str, old: str) -> None:
    assert client_without_token.get(new).status_code == 401
    assert client_without_token.get(old).status_code == 401


@pytest.mark.parametrize(("method", "new", "old"), RENAMED_ROUTES)
def test_cors_preflight_works_on_both_names(method: str, new: str, old: str) -> None:
    origins = get_settings().cors_origins_list
    if not origins:
        pytest.skip("CORS_ORIGINS vacío en este entorno")
    client = TestClient(app)
    headers = {"Origin": origins[0], "Access-Control-Request-Method": method, "Access-Control-Request-Headers": "authorization"}

    for path in (new, old):
        response = client.options(path.format(conversation_id=uuid.uuid4()), headers=headers)
        assert response.status_code == 200, path
        assert response.headers["access-control-allow-origin"] == origins[0]
        assert method in response.headers["access-control-allow-methods"]
