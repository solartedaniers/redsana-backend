"""Implementaciones de las interfaces de redsana_ai que llaman al servicio de IA: quien las usa no nota la diferencia."""

from datetime import datetime
from typing import Any

from redsana_ai import (
    AnomalyDetector,
    BriefingLanguage,
    ChatTurn,
    DeviationClassification,
    NetworkMetricVector,
    OutageDetector,
    OutageEpisode,
    OutageSample,
    SecurityBriefing,
    SecurityChat,
)

from app.ai_gateway.ai_service_client import AiServiceClient
from app.ai_gateway.ai_service_errors import AiServiceResponseError
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow


class RemoteSecurityChat(SecurityChat):
    def __init__(self, client: AiServiceClient, usage_window: InteractiveUsageWindow) -> None:
        self._client = client
        self._usage_window = usage_window

    def ask(
        self, user_context: str, history: list[ChatTurn], user_message: str, topic_context: str | None = None
    ) -> str:
        # Un chat es uso interactivo: mantiene abierta la ventana de los detectores aunque la llamada falle.
        self._usage_window.record_use()
        payload = self._client.post(
            "/v1/chat",
            {
                "user_context": user_context,
                "history": [{"role": turn.role, "content": turn.content} for turn in history],
                "user_message": user_message,
                "topic_context": topic_context,
            },
        )
        return _read_text(payload, "reply")


class RemoteSecurityBriefing(SecurityBriefing):
    def __init__(self, client: AiServiceClient, usage_window: InteractiveUsageWindow) -> None:
        self._client = client
        self._usage_window = usage_window

    def write(self, user_context: str, language: BriefingLanguage) -> str:
        self._usage_window.record_use()
        payload = self._client.post("/v1/briefing", {"user_context": user_context, "language": language})
        return _read_text(payload, "text")


class RemoteAnomalyDetector(AnomalyDetector):
    def __init__(self, client: AiServiceClient) -> None:
        self._client = client

    def evaluate(
        self, history: list[NetworkMetricVector], latest: NetworkMetricVector
    ) -> DeviationClassification | None:
        payload = self._client.post(
            "/v1/anomaly/evaluate", {"history": [list(sample) for sample in history], "latest": list(latest)}
        )
        classification = payload.get("classification")
        if classification is None:
            return None
        try:
            return DeviationClassification(
                deviating_metric=classification["deviating_metric"],
                severity=classification["severity"],
                current=float(classification["current"]),
                typical=float(classification["typical"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AiServiceResponseError(f"unexpected anomaly classification: {classification}") from error


class RemoteOutageDetector(OutageDetector):
    def __init__(self, client: AiServiceClient) -> None:
        self._client = client

    def detect(self, window: list[OutageSample]) -> OutageEpisode | None:
        payload = self._client.post(
            "/v1/outage/detect",
            {"window": [{"recorded_at": at.isoformat(), "packet_loss_percent": loss} for at, loss in window]},
        )
        episode = payload.get("episode")
        if episode is None:
            return None
        try:
            return OutageEpisode(
                started_at=datetime.fromisoformat(episode["started_at"]),
                recovered_at=datetime.fromisoformat(episode["recovered_at"]),
                duration_minutes=int(episode["duration_minutes"]),
                severity=episode["severity"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AiServiceResponseError(f"unexpected outage episode: {episode}") from error


def _read_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise AiServiceResponseError(f"AI service response without a text {key!r}")
    return value
