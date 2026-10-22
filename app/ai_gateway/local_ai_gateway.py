from collections.abc import Callable

from redsana_ai import (
    AnomalyDetector,
    ChatEngine,
    EngineSecurityBriefing,
    EngineSecurityChat,
    IsolationForestAnomalyDetector,
    OutageDetector,
    SecurityBriefing,
    SecurityChat,
    StreakOutageDetector,
)

from app.ai_gateway.ai_gateway import AiAvailability, AiGateway


class LocalAiGateway(AiGateway):
    """El comportamiento de siempre: el paquete corre en este proceso, así que la IA está lista desde que arranca."""

    def __init__(self, chat_engine_factory: Callable[[], ChatEngine]) -> None:
        # Fábrica y no instancia: los detectores en segundo plano no necesitan un motor de chat.
        self._chat_engine_factory = chat_engine_factory

    def security_chat(self) -> SecurityChat:
        return EngineSecurityChat(self._chat_engine_factory())

    def security_briefing(self) -> SecurityBriefing:
        return EngineSecurityBriefing(self._chat_engine_factory())

    def anomaly_detector(self) -> AnomalyDetector:
        return IsolationForestAnomalyDetector()

    def outage_detector(self) -> OutageDetector:
        return StreakOutageDetector()

    def status(self) -> AiAvailability:
        return "ready"

    def start_warm_up(self) -> None:
        # Nada que despertar: el paquete ya está cargado en este proceso.
        return None
