"""Rangos y pesos del puntaje de seguridad: una sola fuente en Settings, publicada en /score-config."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_claims
from app.domain.security_analyzers import TechnicalEvidence, default_technical_analyzers
from app.domain.security_score_config import SecurityScoreConfig
from app.main import app
from app.models.base import Base
from app.models.role import Role
from app.services.network_security_score_service import NetworkSecurityScoreService

URL = "/api/security-assessments/score-config"
ALL_YES = {"default-password": "yes", "firmware-updated": "yes", "guest-network": "yes", "remote-management-off": "yes"}
WEP = TechnicalEvidence(wifi_encryption_raw="WEP", router_open_ports=None)


@pytest.fixture()
def fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _client(with_claims: bool) -> Iterator[TestClient]:
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
    if with_claims:
        app.dependency_overrides[get_current_claims] = lambda: {"sub": str(uuid.uuid4()), "email": "o@example.com"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    yield from _client(with_claims=True)


@pytest.fixture()
def client_without_claims_override() -> Iterator[TestClient]:
    yield from _client(with_claims=False)


def test_defaults_are_the_values_the_frontend_had(fresh_settings: None) -> None:
    assert get_settings().security_score_config == SecurityScoreConfig(
        good_min=80, warning_min=50, questionnaire_weight_percent=30, technical_weight_percent=70
    )


def test_endpoint_publishes_the_configured_values(client: TestClient, fresh_settings: None) -> None:
    response = client.get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "good_min": 80,
        "warning_min": 50,
        "questionnaire_weight_percent": 30,
        "technical_weight_percent": 70,
    }


def test_endpoint_follows_the_environment(
    client: TestClient, fresh_settings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECURITY_SCORE_GOOD_MIN", "90")
    monkeypatch.setenv("SECURITY_SCORE_QUESTIONNAIRE_WEIGHT_PERCENT", "40")
    monkeypatch.setenv("SECURITY_SCORE_TECHNICAL_WEIGHT_PERCENT", "60")
    get_settings.cache_clear()

    body = client.get(URL).json()

    assert (body["good_min"], body["questionnaire_weight_percent"], body["technical_weight_percent"]) == (90, 40, 60)


def test_endpoint_without_token_is_unauthorized(client_without_claims_override: TestClient) -> None:
    assert client_without_claims_override.get(URL).status_code == 401


def test_the_score_uses_the_configured_weights() -> None:
    # Cuestionario 100 y técnico 10 (WEP): 30/70 → 37; 50/50 → 55.
    default = NetworkSecurityScoreService(default_technical_analyzers())
    even = NetworkSecurityScoreService(
        default_technical_analyzers(),
        SecurityScoreConfig(good_min=80, warning_min=50, questionnaire_weight_percent=50, technical_weight_percent=50),
    )

    assert default.evaluate(ALL_YES, WEP).score == 37
    assert even.evaluate(ALL_YES, WEP).score == 55


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ({"SECURITY_SCORE_WARNING_MIN": "90"}, "SECURITY_SCORE_WARNING_MIN"),
        ({"SECURITY_SCORE_GOOD_MIN": "101"}, "SECURITY_SCORE_WARNING_MIN"),
        ({"SECURITY_SCORE_WARNING_MIN": "0"}, "SECURITY_SCORE_WARNING_MIN"),
        ({"SECURITY_SCORE_TECHNICAL_WEIGHT_PERCENT": "60"}, "add up to 100"),
        (
            {"SECURITY_SCORE_QUESTIONNAIRE_WEIGHT_PERCENT": "-10", "SECURITY_SCORE_TECHNICAL_WEIGHT_PERCENT": "110"},
            "add up to 100",
        ),
    ],
)
def test_incoherent_values_are_rejected(
    fresh_settings: None, monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], message: str
) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        get_settings()
