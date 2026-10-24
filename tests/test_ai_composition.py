"""Sin base ni red: AI_MODE elige el gateway en el único punto de composición, que también arma el asistente del chat."""

from datetime import timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from redsana_ai import ChatEngine, ChatTurn, IsolationForestAnomalyDetector, StreakOutageDetector

from app.ai_gateway.local_ai_gateway import LocalAiGateway
from app.ai_gateway.remote_ai_gateway import RemoteAiGateway
from app.ai_gateway.windowed_detectors import WindowedAnomalyDetector, WindowedOutageDetector
from app.core import ai_composition
from app.core.config import Settings

_REQUIRED = {
    "database_url": "postgresql+psycopg2://test:test@127.0.0.1:1/test",
    "supabase_url": "https://example.invalid",
    "supabase_service_role_key": "test-service-role-key",
    "network_id_secret": "test-network-id-secret",
}


class _EchoEngine(ChatEngine):
    def complete(self, system_prompt: str, turns: list[ChatTurn]) -> str:
        return turns[-1].content


def _use_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    settings = Settings(_env_file=None, **_REQUIRED, **overrides)
    monkeypatch.setattr(ai_composition, "get_settings", lambda: settings)
    ai_composition._remote_ai_gateway.cache_clear()


@pytest.fixture(autouse=True)
def _clear_remote_gateway():
    yield
    ai_composition._remote_ai_gateway.cache_clear()


def test_local_mode_uses_the_package_with_the_injected_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_settings(monkeypatch, groq_api_key="test-groq-key")

    gateway = ai_composition.get_ai_gateway(_EchoEngine())

    assert isinstance(gateway, LocalAiGateway)
    assert gateway.security_chat().ask("", [], "hola") == "hola"


def test_local_mode_background_detectors_are_the_package_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_settings(monkeypatch, groq_api_key="test-groq-key")

    assert isinstance(ai_composition.build_anomaly_detector(), IsolationForestAnomalyDetector)
    assert isinstance(ai_composition.build_outage_detector(), StreakOutageDetector)


def test_remote_mode_shares_one_gateway_between_requests_and_background_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_settings(monkeypatch, ai_mode="remote", ai_service_url="https://ai.example.invalid", ai_service_api_key="key")

    from_request = ai_composition.get_ai_gateway(_EchoEngine())
    from_background = ai_composition.build_ai_gateway()

    assert isinstance(from_request, RemoteAiGateway)
    # La misma instancia: así un chat abre la ventana que luego leen los detectores en segundo plano.
    assert from_request is from_background


def test_remote_mode_background_detectors_are_windowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_settings(monkeypatch, ai_mode="remote", ai_service_url="https://ai.example.invalid", ai_service_api_key="key")

    assert isinstance(ai_composition.build_anomaly_detector(), WindowedAnomalyDetector)
    assert isinstance(ai_composition.build_outage_detector(), WindowedOutageDetector)


def test_the_chat_assistant_is_built_here_with_the_gateway_ai_and_the_browser_timezone() -> None:
    gateway = LocalAiGateway(lambda: _EchoEngine())
    with Session(create_engine("sqlite://")) as db:
        assistant = ai_composition.build_security_assistant(gateway, db, utc_offset_minutes=300)

        context = assistant._context_builder
        assert type(assistant._chat) is type(gateway.security_chat())
        assert type(assistant._briefing) is type(gateway.security_briefing())
        # getTimezoneOffset() de Colombia es 300: UTC-5.
        assert context._user_timezone == timezone(timedelta(hours=-5))
        assert all(
            repository._db is db
            for repository in (
                context._device_repository,
                context._alert_repository,
                context._network_metrics_repository,
            )
        )
