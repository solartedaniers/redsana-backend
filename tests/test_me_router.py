"""/api/users/me y su alias /api/me (instalador 0.1.5) responden lo mismo; solo la ruta nueva se documenta."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.role import Role

CLAIMS = {"sub": str(uuid.uuid4()), "email": "owner@example.com"}


@pytest.fixture()
def client():
    # SQLite en memoria con los roles: /api/users/me pasa por get_current_user, que crea el usuario en la base.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
        db.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: CLAIMS
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


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
