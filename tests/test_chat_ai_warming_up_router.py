"""De punta a punta en el router con SQLite en memoria: si el servicio de IA duerme, el chat y el resumen
 responden "encendiendo" (503 con Retry-After) en vez de un error, y un fallo real de Groq sigue siendo 502."""
from redsana_ai import AnomalyDetector, OutageDetector, SecurityBriefing, SecurityChat
from test_chat_conversations_router import AUTH, _make_client, _submit_assessment

from app.ai_gateway.ai_gateway import AiAvailability, AiGateway
from app.ai_gateway.ai_service_errors import AiServiceChatEngineError, AiServiceUnavailableError
from app.core.ai_composition import get_ai_gateway
from app.main import app
from app.models.base import Base


class _FailingChat(SecurityChat):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def ask(self, user_context, history, user_message, topic_context=None) -> str:
        raise self._error


class _FailingBriefing(SecurityBriefing):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def write(self, user_context, language) -> str:
        raise self._error


class _FailingGateway(AiGateway):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def security_chat(self) -> SecurityChat:
        return _FailingChat(self._error)

    def security_briefing(self) -> SecurityBriefing:
        return _FailingBriefing(self._error)

    def anomaly_detector(self) -> AnomalyDetector:
        raise AssertionError("not used by the chat")

    def outage_detector(self) -> OutageDetector:
        raise AssertionError("not used by the chat")

    def status(self) -> AiAvailability:
        return "warming_up"

    def start_warm_up(self) -> None:
        return None


def _client_with(error: Exception):
    client, engine = _make_client()
    app.dependency_overrides[get_ai_gateway] = lambda: _FailingGateway(error)
    return client, engine


def test_a_sleeping_ai_service_makes_the_chat_answer_warming_up():
    client, engine = _client_with(AiServiceUnavailableError("asleep"))
    try:
        conversation_id = client.post("/api/conversations", headers=AUTH).json()["id"]

        response = client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "hola"}, headers=AUTH)

        assert response.status_code == 503
        assert response.json() == {"detail": "ai_warming_up"}
        assert int(response.headers["Retry-After"]) >= 1
        # Nada quedó guardado: al reintentar cuando la IA esté lista la pregunta no aparece dos veces.
        assert client.get(f"/api/conversations/{conversation_id}/messages", headers=AUTH).json() == []
        assert client.get("/api/conversations", headers=AUTH).json()[0]["title"] is None
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_sleeping_ai_service_makes_the_briefing_answer_warming_up_and_leaves_nothing():
    client, engine = _client_with(AiServiceUnavailableError("asleep"))
    try:
        assessment = _submit_assessment(client)

        response = client.post(
            "/api/conversations/briefings", json={"assessment_id": assessment["id"], "language": "es"}, headers=AUTH
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "ai_warming_up"}
        assert client.get("/api/conversations", headers=AUTH).json() == []
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_chat_engine_failure_inside_the_service_is_still_a_502():
    client, engine = _client_with(AiServiceChatEngineError("groq down"))
    try:
        conversation_id = client.post("/api/conversations", headers=AUTH).json()["id"]

        response = client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "hola"}, headers=AUTH)

        assert response.status_code == 502
        assert "groq down" not in response.text
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
