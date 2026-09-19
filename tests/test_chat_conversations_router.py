"""E2E a nivel de router con un GroqClient falso (dependency_overrides) y SQLite
en memoria, mismo patron que test_security_assessment_router.py."""
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
from app.models.role import Role

OWNER_USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()


class _StubGroqClient:
    def __init__(self, reply: str | None = None, error: str | None = None) -> None:
        self._reply = reply
        self._error = error

    def chat(self, system_prompt: str, user_message: str) -> str:
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
        app.dependency_overrides[get_groq_client] = lambda: stub
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
        assert sent.json() == {"reply": "tienes 0 dispositivos conectados"}

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
