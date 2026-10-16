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
        warm_up_probe_timeout_seconds: float,
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
        self._warm_up_probe_timeout_seconds = warm_up_probe_timeout_seconds
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
        return self._probe(self._status_timeout_seconds)

    def _probe(self, timeout_seconds: float) -> AiAvailability:
        try:
            return "ready" if self._status_client.health(timeout_seconds) else "warming_up"
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
            logger.info("AI warm-up already running, skipping")
            return
        try:
            started = self._clock()
            deadline = started + self._warm_up_timeout_seconds
            attempt = 0
            while True:
                attempt += 1
                # Dejo la petición abierta mientras Render despierta el servicio, sin pasarme del tope del calentamiento.
                timeout = min(self._warm_up_probe_timeout_seconds,
                              max(deadline - self._clock(), self._status_timeout_seconds))
                availability = self._probe(timeout)
                logger.info("AI warm-up probe %d: %s (timeout %.0fs, %.1fs since start)",
                            attempt, availability, timeout, self._clock() - started)
                if availability != "warming_up" or self._clock() >= deadline:
                    break
                self._sleep(self._warm_up_poll_seconds)
            logger.info("AI warm-up finished: %s after %d probes and %.1fs", availability, attempt, self._clock() - started)
        finally:
            self._warm_up_lock.release()
