import logging
import threading
import time
from collections.abc import Callable

from redsana_ai import AnomalyDetector, OutageDetector, SecurityBriefing, SecurityChat

from app.ai_gateway.ai_gateway import AiAvailability, AiGateway
from app.ai_gateway.ai_service_client import AiServiceClient
from app.ai_gateway.ai_service_errors import AiServiceError, AiServiceUnavailableError
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.remote_ai_adapters import (
    RemoteAnomalyDetector,
    RemoteOutageDetector,
    RemoteSecurityBriefing,
    RemoteSecurityChat,
)
from app.ai_gateway.windowed_detectors import WindowedAnomalyDetector, WindowedOutageDetector

logger = logging.getLogger(__name__)


class RemoteAiGateway(AiGateway):
    """La IA vive en el servicio aparte: chat y resumen siempre van allí; los detectores en segundo plano solo dentro
     de la ventana de uso interactivo, y si no con el paquete local."""

    def __init__(
        self,
        client: AiServiceClient,
        status_client: AiServiceClient,
        local_fallback: AiGateway,
        usage_window: InteractiveUsageWindow,
        status_timeout_seconds: float,
        warm_up_timeout_seconds: float,
        warm_up_poll_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        # Cliente sin reintentos: el estado se consulta seguido y debe responder rápido aunque el servicio duerma.
        self._status_client = status_client
        self._local_fallback = local_fallback
        self._usage_window = usage_window
        self._status_timeout_seconds = status_timeout_seconds
        self._warm_up_timeout_seconds = warm_up_timeout_seconds
        self._warm_up_poll_seconds = warm_up_poll_seconds
        self._clock = clock
        self._sleep = sleep
        self._warm_up_lock = threading.Lock()

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
        try:
            return "ready" if self._status_client.health(self._status_timeout_seconds) else "warming_up"
        except AiServiceUnavailableError:
            # Dormido o arrancando en Render: para el usuario es "encendiendo", no un error.
            return "warming_up"
        except AiServiceError as error:
            logger.warning("AI service status check failed: %s", error)
            return "unavailable"

    def warm_up(self) -> None:
        # El calentamiento es uso interactivo: abre la ventana para que los detectores aprovechen el servicio despierto.
        self._usage_window.record_use()
        # Si ya hay un calentamiento en curso no lanzo otro: varios usuarios a la vez despertarían lo mismo.
        if not self._warm_up_lock.acquire(blocking=False):
            return
        try:
            deadline = self._clock() + self._warm_up_timeout_seconds
            while self.status() == "warming_up" and self._clock() < deadline:
                self._sleep(self._warm_up_poll_seconds)
        finally:
            self._warm_up_lock.release()
