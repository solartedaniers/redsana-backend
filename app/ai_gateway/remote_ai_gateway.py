import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from redsana_ai import AnomalyDetector, OutageDetector, SecurityBriefing, SecurityChat

from app.ai_gateway.ai_gateway import AiAvailability, AiGateway, AiUnavailableReason
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


@dataclass(frozen=True)
class WarmUpSchedule:
    """Tiempos del calentamiento, todos desde la configuración."""

    timeout_seconds: float
    probe_timeout_seconds: float
    backoff_seconds: float
    max_backoff_seconds: float
    backoff_factor: float


@dataclass(frozen=True)
class _Probe:
    availability: AiAvailability
    reason: AiUnavailableReason | None = None
    retry_after_seconds: float | None = None


def _start_daemon_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="ai-warm-up", daemon=True).start()


class RemoteAiGateway(AiGateway):
    """La IA vive en el servicio aparte: chat y resumen siempre van allí; los detectores en segundo plano solo dentro
     de la ventana de uso interactivo, y si no con el paquete local.

    El estado de la IA vive en memoria: lo actualiza un único calentamiento en segundo plano y status() lo lee, así
    las consultas del frontend no le llegan al servicio mientras Render lo despierta (eso provocaba sus 429)."""

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
        start_thread: Callable[[Callable[[], None]], None] = _start_daemon_thread,
    ) -> None:
        self._client = client
        # Cliente sin reintentos: cada consulta del calentamiento decide por sí misma cuánto esperar.
        self._status_client = status_client
        self._local_fallback = local_fallback
        self._usage_window = usage_window
        self._status_timeout_seconds = status_timeout_seconds
        self._status_cache_seconds = status_cache_seconds
        self._schedule = warm_up_schedule
        self._clock = clock
        self._sleep = sleep
        self._start_thread = start_thread
        # ponytail: estado en memoria del proceso; con varios workers cada uno calentaría por su cuenta (Render free usa uno).
        self._state_lock = threading.Lock()
        self._warming_up = False
        self._availability: AiAvailability = "warming_up"
        self._reason: AiUnavailableReason | None = None
        self._checked_at: float | None = None

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
        with self._state_lock:
            if self._warming_up:
                return "warming_up"
            # "No disponible" se mantiene hasta que se pida otro calentamiento (Reintentar): consultar no lo cambia.
            if self._availability == "unavailable" and self._checked_at is not None:
                return "unavailable"
            if self._checked_at is not None and self._clock() - self._checked_at <= self._status_cache_seconds:
                return self._availability
        # Sin calentamiento en curso y con el dato vencido: una sola consulta corta, que queda en caché.
        probe = self._probe(self._status_timeout_seconds)
        with self._state_lock:
            if not self._warming_up:
                self._remember(probe)
        return probe.availability

    def unavailable_reason(self) -> AiUnavailableReason | None:
        with self._state_lock:
            return self._reason if self._availability == "unavailable" else None

    def start_warm_up(self) -> None:
        with self._state_lock:
            if self._warming_up:
                logger.info("AI warm-up already running, skipping")
                return
            was_ready = self._availability == "ready"
        # Si ya estaba lista, confirmarlo con una consulta corta evita mostrar "encendiendo" sin motivo.
        if was_ready and self.status() == "ready":
            return
        with self._state_lock:
            if self._warming_up:
                return
            self._warming_up = True
            self._availability, self._reason = "warming_up", None
        self._start_thread(self._run_warm_up)

    def _run_warm_up(self) -> None:
        schedule = self._schedule
        started = self._clock()
        deadline = started + schedule.timeout_seconds
        backoff = schedule.backoff_seconds
        attempt = 0
        result = _Probe("unavailable", "timed_out")
        try:
            while True:
                attempt += 1
                # Una petición larga y paciente, como la del navegador: Render la retiene mientras despierta el servicio.
                timeout = min(schedule.probe_timeout_seconds, max(deadline - self._clock(), self._status_timeout_seconds))
                probe = self._probe(timeout)
                logger.info("AI warm-up probe %d: %s (timeout %.0fs, %.1fs since start)",
                            attempt, probe.availability, timeout, self._clock() - started)
                if probe.availability != "warming_up":
                    result = probe
                    break
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                # Si Render pidió esperar (Retry-After) lo respeto; si no, espera creciente con tope.
                self._sleep(min(max(backoff, probe.retry_after_seconds or 0), remaining))
                backoff = min(backoff * schedule.backoff_factor, schedule.max_backoff_seconds)
        finally:
            with self._state_lock:
                self._remember(result)
                self._warming_up = False
        if result.availability == "ready":
            # La IA está despierta: desde ahora los detectores pueden usarla durante la ventana de uso interactivo.
            self._usage_window.record_use()
        logger.info("AI warm-up finished: %s (%s) after %d probes and %.1fs",
                    result.availability, result.reason, attempt, self._clock() - started)

    def _remember(self, probe: _Probe) -> None:
        self._availability, self._reason, self._checked_at = probe.availability, probe.reason, self._clock()

    def _probe(self, timeout_seconds: float) -> _Probe:
        try:
            return _Probe("ready" if self._status_client.health(timeout_seconds) else "warming_up")
        except AiServiceUnavailableError as error:
            # Dormido o arrancando en Render (429, 50x, sin respuesta): para el usuario es "encendiendo", no un error.
            logger.info("AI service still waking up: %s", error)
            return _Probe("warming_up", retry_after_seconds=error.retry_after_seconds)
        except AiServiceError as error:
            logger.warning("AI service status check failed: %s", error)
            return _Probe("unavailable", "service_error")
