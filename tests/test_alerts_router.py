"""El endpoint de alertas de prueba solo responde si la configuración lo habilita."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.authorization import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models.base import Base

ALERT_PAYLOAD = {
    "owner_id": str(uuid.uuid4()),
    "type": "outage",
    "severity": "critical",
    "message_key": "user.alertsCenter.messages.briefOutage",
    "message_params": {"minutes": 2},
}


def _client(test_alerts_enabled: bool):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(enable_test_alerts_endpoint=test_alerts_enabled)
    return TestClient(app), engine


@pytest.fixture()
def make_client():
    engines = []

    def factory(test_alerts_enabled: bool) -> TestClient:
        client, engine = _client(test_alerts_enabled)
        engines.append(engine)
        return client

    try:
        yield factory
    finally:
        app.dependency_overrides.clear()
        for engine in engines:
            Base.metadata.drop_all(engine)


def test_test_alerts_endpoint_is_hidden_by_default(make_client) -> None:
    response = make_client(False).post("/api/alerts", json=ALERT_PAYLOAD)

    assert response.status_code == 404


def test_test_alerts_endpoint_works_when_enabled_in_development(make_client) -> None:
    response = make_client(True).post("/api/alerts", json=ALERT_PAYLOAD)

    assert response.status_code == 201
    assert response.json()["message_key"] == ALERT_PAYLOAD["message_key"]


def test_setting_defaults_to_disabled() -> None:
    from app.core.config import Settings

    assert Settings.model_fields["enable_test_alerts_endpoint"].default is False
