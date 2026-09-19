"""E2E a nivel de router con un GroqClient falso (dependency_overrides), igual
patron que test_security_assessment_router.py: no pega a la red real, solo
valida que el router conecte auth + service + client correctamente."""
from fastapi.testclient import TestClient

from app.core.groq_client import GroqClientError, get_groq_client
from app.core.security import get_current_claims
from app.main import app


class _StubGroqClient:
    def __init__(self, reply: str | None = None, error: str | None = None) -> None:
        self._reply = reply
        self._error = error

    def chat(self, system_prompt: str, user_message: str) -> str:
        if self._error:
            raise GroqClientError(self._error)
        return self._reply


def _override_claims():
    return {"sub": "user-1", "email": "user@example.com"}


def test_chat_returns_reply_from_service():
    app.dependency_overrides[get_current_claims] = _override_claims
    app.dependency_overrides[get_groq_client] = lambda: _StubGroqClient(reply="usa WPA3 si tu router lo soporta")
    try:
        response = TestClient(app).post(
            "/api/security-assistant/chat", json={"message": "que cifrado uso?"}, headers={"Authorization": "Bearer fake"}
        )
        assert response.status_code == 200
        assert response.json() == {"reply": "usa WPA3 si tu router lo soporta"}
    finally:
        app.dependency_overrides.clear()


def test_chat_without_token_is_unauthorized():
    response = TestClient(app).post("/api/security-assistant/chat", json={"message": "hola"})
    assert response.status_code == 401


def test_chat_propagates_groq_failure_as_502():
    app.dependency_overrides[get_current_claims] = _override_claims
    app.dependency_overrides[get_groq_client] = lambda: _StubGroqClient(error="no se pudo contactar a Groq")
    try:
        response = TestClient(app).post(
            "/api/security-assistant/chat", json={"message": "hola"}, headers={"Authorization": "Bearer fake"}
        )
        assert response.status_code == 502
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    print("Run via pytest: python -m pytest tests/test_security_chat_router.py")
