"""/api/users/me y su alias /api/me (instalador 0.1.5) responden lo mismo; solo la ruta nueva se documenta."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_claims
from app.main import app
from app.routers import me
from app.services.user_service import UserService
from tests.test_user_service import FakeUserRepository

CLAIMS = {"sub": str(uuid.uuid4()), "email": "owner@example.com"}


@pytest.fixture()
def client():
    service = UserService(FakeUserRepository())
    app.dependency_overrides[get_current_claims] = lambda: CLAIMS
    app.dependency_overrides[me._get_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/api/users/me", "/api/me"])
def test_both_paths_read_the_current_user(client, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.json()["email"] == "owner@example.com"


@pytest.mark.parametrize("path", ["/api/users/me", "/api/me"])
def test_both_paths_update_the_current_user(client, path: str) -> None:
    client.get(path)  # como en la app: el perfil se crea al iniciar sesión, antes de editarlo
    response = client.patch(path, json={"full_name": "Nombre nuevo"})

    assert response.status_code == 200
    assert client.get("/api/users/me").json()["full_name"] == "Nombre nuevo"


def test_only_the_new_path_is_documented() -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/api/users/me"]) == {"get", "patch"}
    assert "/api/me" not in paths
