"""E2E a nivel de router con un GroqClient falso (dependency_overrides) y SQLite
en memoria, mismo patron que test_security_assessment_router.py."""
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.chat_engine import ChatEngine, ChatTurn
from app.core.groq_client import GroqClientError, get_chat_engine
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.role import Role

OWNER_USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()


class _StubGroqClient(ChatEngine):
    def __init__(self, reply: str | None = None, error: str | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls: list[tuple[str, list[ChatTurn]]] = []

    def complete(self, system_prompt: str, turns: list[ChatTurn]) -> str:
        self.calls.append((system_prompt, turns))
        if self._error:
            raise GroqClientError(self._error)
        return self._reply


def _override_claims():
    return {"sub": str(OWNER_USER_ID), "email": "owner@example.com"}


def _override_other_claims():
    return {"sub": str(OTHER_USER_ID), "email": "other@example.com"}


def _make_client(stub: _StubGroqClient | None = None):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session_factory() as db:
        db.add(Role(id=1, name="standard"))
        db.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = _override_claims
    if stub is not None:
        app.dependency_overrides[get_chat_engine] = lambda: stub
    return TestClient(app), engine


def test_create_list_and_rename_conversation():
    client, engine = _make_client()
    try:
        created = client.post("/api/conversations", headers={"Authorization": "Bearer fake"})
        assert created.status_code == 201
        assert created.json()["title"] is None
        conversation_id = created.json()["id"]

        listed = client.get("/api/conversations", headers={"Authorization": "Bearer fake"})
        assert listed.status_code == 200
        assert [c["id"] for c in listed.json()] == [conversation_id]

        renamed = client.patch(
            f"/api/conversations/{conversation_id}", json={"title": "Mi red"}, headers={"Authorization": "Bearer fake"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Mi red"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_send_message_persists_history_and_autotitles():
    stub = _StubGroqClient(reply="tienes 0 dispositivos conectados")
    client, engine = _make_client(stub)
    try:
        conversation_id = client.post("/api/conversations", headers={"Authorization": "Bearer fake"}).json()["id"]

        sent = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"message": "cuantos dispositivos tengo?"},
            headers={"Authorization": "Bearer fake"},
        )
        assert sent.status_code == 200
        assert sent.json() == {"reply": "tienes 0 dispositivos conectados", "notice_key": None, "notice_params": None}

        messages = client.get(
            f"/api/conversations/{conversation_id}/messages", headers={"Authorization": "Bearer fake"}
        ).json()
        assert [(m["role"], m["content"]) for m in messages] == [
            ("user", "cuantos dispositivos tengo?"),
            ("assistant", "tienes 0 dispositivos conectados"),
        ]

        conversation = client.get("/api/conversations", headers={"Authorization": "Bearer fake"}).json()[0]
        assert conversation["title"] == "cuantos dispositivos tengo?"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_cannot_access_another_owners_conversation():
    client, engine = _make_client()
    try:
        conversation_id = client.post("/api/conversations", headers={"Authorization": "Bearer fake"}).json()["id"]

        app.dependency_overrides[get_current_claims] = _override_other_claims
        response = client.get(f"/api/conversations/{conversation_id}/messages", headers={"Authorization": "Bearer fake"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_send_message_to_unknown_conversation_is_404():
    stub = _StubGroqClient(reply="hola")
    client, engine = _make_client(stub)
    try:
        response = client.post(
            f"/api/conversations/{uuid.uuid4()}/messages",
            json={"message": "hola"},
            headers={"Authorization": "Bearer fake"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_endpoints_without_token_are_unauthorized():
    assert TestClient(app).get("/api/conversations").status_code == 401
    assert TestClient(app).post("/api/conversations").status_code == 401


if __name__ == "__main__":
    print("Run via pytest: python -m pytest tests/test_chat_conversations_router.py")


AUTH = {"Authorization": "Bearer fake"}
ANSWERS = {"default-password": "yes", "firmware-updated": "yes", "guest-network": "no", "remote-management-off": "yes"}


def _submit_assessment(client, **evidence) -> dict:
    return client.post("/api/security-assessments", json={"answers": ANSWERS, **evidence}, headers=AUTH).json()


def test_the_model_receives_the_recent_conversation_history():
    stub = _StubGroqClient(reply="ok")
    client, engine = _make_client(stub)
    try:
        conversation_id = client.post("/api/conversations", headers=AUTH).json()["id"]
        client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "tengo Telnet abierto"}, headers=AUTH)
        client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "como cierro eso?"}, headers=AUTH)

        _, turns = stub.calls[-1]
        assert [(t.role, t.content) for t in turns] == [
            ("user", "tengo Telnet abierto"),
            ("assistant", "ok"),
            ("user", "como cierro eso?"),
        ]
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_message_with_a_password_is_never_stored_nor_sent_to_the_model():
    stub = _StubGroqClient(reply="no deberia llamarse")
    client, engine = _make_client(stub)
    try:
        conversation_id = client.post("/api/conversations", headers=AUTH).json()["id"]

        sent = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"message": "la clave de mi router es Casa2024"},
            headers=AUTH,
        )

        assert sent.json() == {"reply": None, "notice_key": "user.securityAssistant.chat.passwordWarning", "notice_params": None}
        assert stub.calls == []
        assert client.get(f"/api/conversations/{conversation_id}/messages", headers=AUTH).json() == []
        # Tampoco queda como título de la conversación.
        assert client.get("/api/conversations", headers=AUTH).json()[0]["title"] is None
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_briefing_is_written_once_per_assessment_with_the_real_score_in_context():
    stub = _StubGroqClient(reply="Tu puntaje es 68. Cierra Telnet.")
    client, engine = _make_client(stub)
    try:
        assessment = _submit_assessment(client, wifi_encryption_raw="WPA2-Personal", router_open_ports=[23])

        first = client.post("/api/conversations/briefings", json={"assessment_id": assessment["id"], "language": "es"}, headers=AUTH)
        again = client.post("/api/conversations/briefings", json={"assessment_id": assessment["id"], "language": "es"}, headers=AUTH)

        assert first.status_code == again.status_code == 200
        assert first.json() == again.json()
        assert len(stub.calls) == 1  # la segunda vez no vuelve a llamar al modelo
        assert first.json()["conversation"]["topic"] == "assessment_briefing"
        assert [(m["role"], m["content"]) for m in first.json()["messages"]] == [("assistant", "Tu puntaje es 68. Cierra Telnet.")]
        system_prompt, _ = stub.calls[0]
        assert f"{assessment['score']}/100" in system_prompt
        assert "23 (Telnet)" in system_prompt
        assert "WPA2-Personal" in system_prompt
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_web_briefing_context_says_honestly_that_there_is_no_technical_analysis():
    stub = _StubGroqClient(reply="resumen")
    client, engine = _make_client(stub)
    try:
        assessment = _submit_assessment(client)
        client.post("/api/conversations/briefings", json={"assessment_id": assessment["id"], "language": "en"}, headers=AUTH)

        system_prompt, turns = stub.calls[0]
        assert "PARCIAL: solo cuestionario" in system_prompt
        assert "ingles" in turns[0].content
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_only_the_latest_own_assessment_can_be_briefed_and_a_model_failure_leaves_nothing():
    client, engine = _make_client(_StubGroqClient(error="groq caido"))
    try:
        old = _submit_assessment(client)
        # SQLite guarda now() con resolución de segundos: sin esta pausa ambas
        # evaluaciones empatan y "la más reciente" sería ambigua (Postgres usa µs).
        time.sleep(1.1)
        latest = _submit_assessment(client)

        stale = client.post("/api/conversations/briefings", json={"assessment_id": old["id"], "language": "es"}, headers=AUTH)
        failed = client.post("/api/conversations/briefings", json={"assessment_id": latest["id"], "language": "es"}, headers=AUTH)

        assert stale.status_code == 404
        assert failed.status_code == 502
        assert client.get("/api/conversations", headers=AUTH).json() == []
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_family_mode_conversation_carries_the_family_dns_guide_in_context():
    stub = _StubGroqClient(reply="Que marca es tu router?")
    client, engine = _make_client(stub)
    try:
        created = client.post("/api/conversations", json={"topic": "family_mode"}, headers=AUTH)
        conversation_id = created.json()["id"]
        client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "no encuentro el DNS"}, headers=AUTH)

        system_prompt, _ = stub.calls[0]
        assert created.json()["topic"] == "family_mode"
        assert "1.1.1.3" in system_prompt and "1.0.0.3" in system_prompt
        assert "5. Guardar los cambios" in system_prompt
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_users_cannot_open_a_briefing_topic_by_hand():
    client, engine = _make_client()
    try:
        response = client.post("/api/conversations", json={"topic": "assessment_briefing"}, headers=AUTH)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_a_wrong_dns_in_a_family_mode_reply_comes_with_the_exact_values_from_the_guide():
    # Respuesta real que dio el modelo: secundario 0.0.0.3 en vez de 1.0.0.3.
    stub = _StubGroqClient(reply="DNS primario: 1.1.1.3 / DNS secundario: **0.0.0.3**")
    client, engine = _make_client(stub)
    try:
        conversation_id = client.post("/api/conversations", json={"topic": "family_mode"}, headers=AUTH).json()["id"]

        sent = client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "que pongo?"}, headers=AUTH).json()

        assert sent["reply"] == "DNS primario: 1.1.1.3 / DNS secundario: 0.0.0.3"  # sin Markdown
        assert sent["notice_key"] == "user.securityAssistant.chat.familyDnsCheck"
        assert sent["notice_params"] == {"primary": "1.1.1.3", "secondary": "1.0.0.3"}
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_correct_family_dns_replies_have_no_notice():
    stub = _StubGroqClient(reply="Entra a 192.168.0.1 y escribe 1.1.1.3 y 1.0.0.3.")
    client, engine = _make_client(stub)
    try:
        conversation_id = client.post("/api/conversations", json={"topic": "family_mode"}, headers=AUTH).json()["id"]

        sent = client.post(f"/api/conversations/{conversation_id}/messages", json={"message": "que pongo?"}, headers=AUTH).json()

        assert sent["notice_key"] is None
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)

