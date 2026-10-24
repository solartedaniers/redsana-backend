"""Sin base: AI_MODE es local por defecto y cada modo exige solo lo que usa."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_REQUIRED = {
    "database_url": "postgresql+psycopg2://test:test@127.0.0.1:1/test",
    "supabase_url": "https://example.invalid",
    "supabase_service_role_key": "test-service-role-key",
    "network_id_secret": "test-network-id-secret",
}
_AI_VARIABLES = ("AI_MODE", "AI_SERVICE_URL", "AI_SERVICE_API_KEY", "GROQ_API_KEY")


@pytest.fixture(autouse=True)
def _clean_ai_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AI_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_local_mode_is_the_default() -> None:
    settings = Settings(_env_file=None, **_REQUIRED, groq_api_key="test-groq-key")

    assert settings.ai_mode == "local"


def test_local_mode_still_requires_the_groq_key() -> None:
    with pytest.raises(ValidationError, match="GROQ_API_KEY"):
        Settings(_env_file=None, **_REQUIRED)


def test_remote_mode_requires_the_service_url_and_key() -> None:
    with pytest.raises(ValidationError, match="AI_SERVICE_URL"):
        Settings(_env_file=None, **_REQUIRED, ai_mode="remote", ai_service_url="http://ai.invalid")


def test_remote_mode_does_not_need_groq() -> None:
    settings = Settings(
        _env_file=None, **_REQUIRED, ai_mode="remote", ai_service_url="http://ai.invalid", ai_service_api_key="key"
    )

    assert settings.ai_mode == "remote"
    assert settings.groq_api_key == ""


def test_an_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **_REQUIRED, groq_api_key="test-groq-key", ai_mode="hybrid")
