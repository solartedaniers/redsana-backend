"""E2E a nivel de router con un GroqClient falso (dependency_overrides) y SQLite
en memoria, mismo patron que test_security_assessment_router.py: no pega a la
red real, solo valida que el router conecte auth + contexto real + client."""
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.groq_client import GroqClientError, get_groq_client
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.device import Device
from app.models.role import Role

OWNER_USER_ID = uuid.uuid4()


class _StubGroqClient:
    """Captura el system_prompt recibido para poder verificar que el contexto
    real (conteo de dispositivos, etc.) sí llegó al modelo."""

    def __init__(self, reply: str | None = None, error: str | None = None) -> None:
        self._reply = reply
        self._error = error
        self.last_system_prompt: str | None = None

    def chat(self, system_prompt: str, user_message: str) -> str:
        self.last_system_prompt = system_prompt
        if self._error:
            raise GroqClientError(self._error)
        return self._reply


def _override_claims():
    return {"sub": str(OWNER_USER_ID), "email": "owner@example.com"}


def _make_client(stub: _StubGroqClient, seed_devices: int = 0):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session_factory() as db:
        db.add(Role(id=1, name="standard"))
        for i in range(seed_devices):
            db.add(Device(owner_id=OWNER_USER_ID, name="", mac_address=f"AA:BB:CC:DD:EE:{i:02X}", ip_address="192.168.0.10"))
        db.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = _override_claims
    app.dependency_overrides[get_groq_client] = lambda: stub
    return TestClient(app), engine


def test_chat_returns_reply_and_injects_real_device_count():
    stub = _StubGroqClient(reply="usa WPA3 si tu router lo soporta")
    client, engine = _make_client(stub, seed_devices=3)
    try:
        response = client.post(
            "/api/security-assistant/chat", json={"message": "cuantos dispositivos tengo?"}, headers={"Authorization": "Bearer fake"}
        )
        assert response.status_code == 200
        assert response.json() == {"reply": "usa WPA3 si tu router lo soporta"}
        assert "Dispositivos: 3 en total" in stub.last_system_prompt
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_chat_without_token_is_unauthorized():
    response = TestClient(app).post("/api/security-assistant/chat", json={"message": "hola"})
    assert response.status_code == 401


def test_chat_propagates_groq_failure_as_502():
    stub = _StubGroqClient(error="no se pudo contactar a Groq")
    client, engine = _make_client(stub)
    try:
        response = client.post(
            "/api/security-assistant/chat", json={"message": "hola"}, headers={"Authorization": "Bearer fake"}
        )
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


if __name__ == "__main__":
    print("Run via pytest: python -m pytest tests/test_security_chat_router.py")
