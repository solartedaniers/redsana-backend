import time
from collections.abc import Callable

from redsana_ai import AnomalyDetector, OutageDetector, SecurityBriefing, SecurityChat

from app.ai_gateway.ai_gateway import AiAvailability, AiGateway, AiUnavailableReason
from app.ai_gateway.ai_service_client import AiServiceClient
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.remote_ai_adapters import (
    RemoteAnomalyDetector,
    RemoteOutageDetector,
    RemoteSecurityBriefing,
    RemoteSecurityChat,
)
from app.ai_gateway.warm_up_controller import WarmUpController, WarmUpSchedule, start_daemon_thread
from app.ai_gateway.windowed_detectors import WindowedAnomalyDetector, WindowedOutageDetector


class RemoteAiGateway(AiGateway):
    """Chat y resumen siempre van al servicio; los detectores solo dentro de la ventana de uso interactivo, para no
    despertarlo con cada medición. Estado y calentamiento: WarmUpController."""

    def __init__(
        self,
        client: AiServiceClient,
        status_client: AiServiceClient,
        local_fallback: AiGateway,
        usage_window: InteractiveUsageWindow,
        status_timeout_seconds: float,
        status_cache_seconds: float,
        warm_up_schedule: WarmUpSchedule,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        start_thread: Callable[[Callable[[], None]], None] = start_daemon_thread,
    ) -> None:
        self._client = client
        self._local_fallback = local_fallback
        self._usage_window = usage_window
        self._warm_up = WarmUpController(
            status_client, usage_window, status_timeout_seconds, status_cache_seconds, warm_up_schedule, clock, sleep,
            start_thread,
        )

    def security_chat(self) -> SecurityChat:
        return RemoteSecurityChat(self._client, self._usage_window)

    def security_briefing(self) -> SecurityBriefing:
        return RemoteSecurityBriefing(self._client, self._usage_window)

    def anomaly_detector(self) -> AnomalyDetector:
        return WindowedAnomalyDetector(
            RemoteAnomalyDetector(self._client), self._local_fallback.anomaly_detector(), self._usage_window
        )

    def outage_detector(self) -> OutageDetector:
        return WindowedOutageDetector(
            RemoteOutageDetector(self._client), self._local_fallback.outage_detector(), self._usage_window
        )

    def status(self) -> AiAvailability:
        return self._warm_up.status()

    def unavailable_reason(self) -> AiUnavailableReason | None:
        return self._warm_up.unavailable_reason()

    def start_warm_up(self) -> None:
        self._warm_up.start()
