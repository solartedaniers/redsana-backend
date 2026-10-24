import logging

from redsana_ai import (
    AnomalyDetector,
    DeviationClassification,
    NetworkMetricVector,
    OutageDetector,
    OutageEpisode,
    OutageSample,
)

from app.ai_gateway.ai_service_errors import AiServiceError
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow

logger = logging.getLogger(__name__)


class WindowedAnomalyDetector(AnomalyDetector):
    """Las evaluaciones corren con cada medición: si llamaran siempre al servicio lo mantendrían despierto. Solo lo uso
    dentro de la ventana de uso interactivo; fuera de ella, o si falla, uso el paquete local (mismo resultado)."""

    def __init__(self, remote: AnomalyDetector, local: AnomalyDetector, usage_window: InteractiveUsageWindow) -> None:
        self._remote = remote
        self._local = local
        self._usage_window = usage_window

    def evaluate(
        self, history: list[NetworkMetricVector], latest: NetworkMetricVector
    ) -> DeviationClassification | None:
        if self._usage_window.is_open():
            try:
                return self._remote.evaluate(history, latest)
            except AiServiceError as error:
                logger.warning("remote anomaly detection failed, using the local package: %s", error)
        return self._local.evaluate(history, latest)


class WindowedOutageDetector(OutageDetector):
    """Igual que WindowedAnomalyDetector, pero aparte para no acoplar los dos detectores."""

    def __init__(self, remote: OutageDetector, local: OutageDetector, usage_window: InteractiveUsageWindow) -> None:
        self._remote = remote
        self._local = local
        self._usage_window = usage_window

    def detect(self, window: list[OutageSample]) -> OutageEpisode | None:
        if self._usage_window.is_open():
            try:
                return self._remote.detect(window)
            except AiServiceError as error:
                logger.warning("remote outage detection failed, using the local package: %s", error)
        return self._local.detect(window)
