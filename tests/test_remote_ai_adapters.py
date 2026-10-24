"""Sin red: un servicio falso que responde con el propio paquete (con el contrato JSON de redsana_ai_service) prueba
que los adaptadores remotos serializan y leen de modo que el resultado es el mismo que en modo local."""

import io
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from redsana_ai import (
    ChatEngine,
    ChatTurn,
    EngineSecurityBriefing,
    EngineSecurityChat,
    IsolationForestAnomalyDetector,
    StreakOutageDetector,
)

from app.ai_gateway.ai_service_client import AiServiceClient
from app.ai_gateway.ai_service_errors import AiServiceResponseError
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.remote_ai_adapters import (
    RemoteAnomalyDetector,
    RemoteOutageDetector,
    RemoteSecurityBriefing,
    RemoteSecurityChat,
)

_BASE_URL = "https://ai.example.invalid"
# Historial estable de una red sana: latencia ~20 ms, jitter ~2 ms y casi sin pérdida.
_HISTORY = [(20.0 + (i % 5) * 0.4, 2.0 + (i % 3) * 0.1, (i % 2) * 0.05) for i in range(60)]
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _RecordingEngine(ChatEngine):
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[ChatTurn]]] = []

    def complete(self, system_prompt: str, turns: list[ChatTurn]) -> str:
        self.calls.append((system_prompt, turns))
        return "## Resumen\nTu puntaje es **68/100**."


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


def _iso(moment: datetime) -> str:
    # pydantic serializa UTC con "Z": lo imito para probar que el backend lo lee igual.
    return moment.isoformat().replace("+00:00", "Z")


class _PackageBackedService:
    """Responde cada ruta del servicio con el paquete, con el mismo contrato JSON que redsana_ai_service."""

    def __init__(self, engine: ChatEngine) -> None:
        self._engine = engine

    def __call__(self, request, timeout: float) -> _Response:
        path = request.full_url.removeprefix(_BASE_URL)
        return _Response(json.dumps(self._answer(path, json.loads(request.data))).encode())

    def _answer(self, path: str, body: dict) -> dict:
        if path == "/v1/chat":
            history = [ChatTurn(turn["role"], turn["content"]) for turn in body["history"]]
            chat = EngineSecurityChat(self._engine)
            return {"reply": chat.ask(body["user_context"], history, body["user_message"], body["topic_context"])}
        if path == "/v1/briefing":
            return {"text": EngineSecurityBriefing(self._engine).write(body["user_context"], body["language"])}
        if path == "/v1/anomaly/evaluate":
            history = [tuple(sample) for sample in body["history"]]
            result = IsolationForestAnomalyDetector().evaluate(history, tuple(body["latest"]))
            return {"classification": None if result is None else asdict(result)}
        if path == "/v1/outage/detect":
            window = [(datetime.fromisoformat(s["recorded_at"]), s["packet_loss_percent"]) for s in body["window"]]
            episode = StreakOutageDetector().detect(window)
            if episode is None:
                return {"episode": None}
            return {
                "episode": {
                    **asdict(episode),
                    "started_at": _iso(episode.started_at),
                    "recovered_at": _iso(episode.recovered_at),
                }
            }
        raise AssertionError(f"unexpected path {path}")


def _client() -> AiServiceClient:
    return AiServiceClient(_BASE_URL, "test-key", 5, max_retries=0, retry_backoff_seconds=0)


def test_remote_chat_matches_the_package_and_opens_the_usage_window() -> None:
    remote_engine, local_engine = _RecordingEngine(), _RecordingEngine()
    window = InteractiveUsageWindow(600)
    history = [ChatTurn("user", "hola"), ChatTurn("assistant", "¿en qué te ayudo?")]

    with patch("urllib.request.urlopen", side_effect=_PackageBackedService(remote_engine)):
        reply = RemoteSecurityChat(_client(), window).ask("- Dispositivos: 3.", history, "¿es segura?", "tema")

    assert reply == EngineSecurityChat(local_engine).ask("- Dispositivos: 3.", history, "¿es segura?", "tema")
    assert remote_engine.calls == local_engine.calls
    assert window.is_open() is True


def test_remote_briefing_matches_the_package_and_opens_the_usage_window() -> None:
    remote_engine, local_engine = _RecordingEngine(), _RecordingEngine()
    window = InteractiveUsageWindow(600)

    with patch("urllib.request.urlopen", side_effect=_PackageBackedService(remote_engine)):
        text = RemoteSecurityBriefing(_client(), window).write("- Puntaje: 68.", "en")

    assert text == EngineSecurityBriefing(local_engine).write("- Puntaje: 68.", "en")
    assert remote_engine.calls == local_engine.calls
    assert window.is_open() is True


@pytest.mark.parametrize("latest", [(21.0, 2.1, 0.05), (400.0, 2.0, 0.0), (20.0, 2.0, 15.0)])
def test_remote_anomaly_detection_matches_the_package(latest: tuple[float, float, float]) -> None:
    with patch("urllib.request.urlopen", side_effect=_PackageBackedService(_RecordingEngine())):
        remote = RemoteAnomalyDetector(_client()).evaluate(_HISTORY, latest)

    assert remote == IsolationForestAnomalyDetector().evaluate(_HISTORY, latest)


@pytest.mark.parametrize(
    "samples",
    [
        [(0, 0.0), (1, 100.0), (2, 100.0), (3, 0.0)],
        [(0, 0.0)] + [(minutes, 100.0) for minutes in range(1, 17)] + [(17, 0.0)],
        [(0, 100.0), (1, 100.0)],
    ],
)
def test_remote_outage_detection_matches_the_package(samples: list[tuple[int, float]]) -> None:
    window = [(_NOW - timedelta(minutes=minutes_ago), loss) for minutes_ago, loss in samples]

    with patch("urllib.request.urlopen", side_effect=_PackageBackedService(_RecordingEngine())):
        remote = RemoteOutageDetector(_client()).detect(window)

    assert remote == StreakOutageDetector().detect(window)


def test_detectors_do_not_open_the_usage_window() -> None:
    window = InteractiveUsageWindow(600)

    with patch("urllib.request.urlopen", side_effect=_PackageBackedService(_RecordingEngine())):
        RemoteAnomalyDetector(_client()).evaluate(_HISTORY, (20.0, 2.0, 0.0))
        RemoteOutageDetector(_client()).detect([(_NOW, 0.0)])

    assert window.is_open() is False


def test_a_reply_without_text_is_a_response_error() -> None:
    with patch("urllib.request.urlopen", return_value=_Response(b'{"reply": null}')):
        with pytest.raises(AiServiceResponseError):
            RemoteSecurityChat(_client(), InteractiveUsageWindow(600)).ask("", [], "hola")


def test_a_malformed_classification_is_a_response_error() -> None:
    with patch("urllib.request.urlopen", return_value=_Response(b'{"classification": {"severity": "critical"}}')):
        with pytest.raises(AiServiceResponseError):
            RemoteAnomalyDetector(_client()).evaluate(_HISTORY, (400.0, 2.0, 0.0))
