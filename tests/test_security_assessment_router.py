"""Sin override de admin: cada usuario solo ve y escribe la suya. SQLite en memoria y token ya decodificado."""
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

OWNER_USER_ID = uuid.uuid4()

ANSWERS_PAYLOAD = {
    "answers": {
        "default-password": "yes",
        "firmware-updated": "no",
        "guest-network": "unknown",
        "remote-management-off": "yes",
    },
    "wifi_encryption_raw": "WPA2",
}


def _sqlite_session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session_factory() as db:
        db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
        db.commit()

    return engine, session_factory


@pytest.fixture()
def client():
    engine, session_factory = _sqlite_session_factory()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_claims():
        return {"sub": str(OWNER_USER_ID), "email": "owner@example.com"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = override_get_current_claims
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_latest_is_null_before_any_submission(client: TestClient) -> None:
    response = client.get("/api/security-assessments/latest", headers={"Authorization": "Bearer fake"})

    assert response.status_code == 200
    assert response.json() is None


def test_submit_then_latest_returns_computed_score(client: TestClient) -> None:
    submit = client.post(
        "/api/security-assessments", json=ANSWERS_PAYLOAD, headers={"Authorization": "Bearer fake"}
    )
    assert submit.status_code == 201
    # Cuestionario: (25 + 20) / 80 = 56; técnico: solo WPA2 = 85. Total: 56 * 30% + 85 * 70% = 76.
    assert submit.json()["score"] == 76
    assert submit.json()["questionnaire_score"] == 56
    assert submit.json()["technical_score"] == 85
    assert submit.json()["is_partial"] is False

    latest = client.get("/api/security-assessments/latest", headers={"Authorization": "Bearer fake"})
    assert latest.status_code == 200
    assert latest.json()["score"] == 76
    recommendation_ids = {r["id"] for r in latest.json()["recommendations"]}
    assert recommendation_ids == {"update-firmware", "check-guest-network"}


def test_post_without_token_is_unauthorized() -> None:
    engine, session_factory = _sqlite_session_factory()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post("/api/security-assessments", json=ANSWERS_PAYLOAD)
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


if __name__ == "__main__":
    print("Run via pytest: python -m pytest tests/test_security_assessment_router.py")


def test_web_submission_reuses_desktop_evidence_through_the_real_repository(client: TestClient) -> None:
    headers = {"Authorization": "Bearer fake"}
    desktop = client.post(
        "/api/security-assessments",
        json={**ANSWERS_PAYLOAD, "router_open_ports": [23]},
        headers=headers,
    ).json()

    web = client.post(
        "/api/security-assessments",
        json={"answers": ANSWERS_PAYLOAD["answers"], "wifi_encryption_raw": None, "router_open_ports": None},
        headers=headers,
    ).json()

    assert web["is_partial"] is False
    assert web["technical_evidence_reused"] is True
    assert web["technical_measured_at"] == desktop["submitted_at"]
    assert web["score"] == desktop["score"]

