from abc import ABC, abstractmethod
from typing import Literal

from redsana_ai import AnomalyDetector, OutageDetector, SecurityBriefing, SecurityChat

AiAvailability = Literal["ready", "warming_up", "unavailable"]


class AiGateway(ABC):
    """Única puerta del backend a la IA: quien la usa pide piezas de redsana_ai sin saber si corren aquí o en el
     servicio aparte."""

    @abstractmethod
    def security_chat(self) -> SecurityChat: ...

    @abstractmethod
    def security_briefing(self) -> SecurityBriefing: ...

    @abstractmethod
    def anomaly_detector(self) -> AnomalyDetector:
        """Para las evaluaciones en segundo plano que corren con cada medición."""

    @abstractmethod
    def outage_detector(self) -> OutageDetector:
        """Para las evaluaciones en segundo plano que corren con cada medición."""

    @abstractmethod
    def status(self) -> AiAvailability:
        """Consulta liviana: nunca lanza, un servicio dormido es "warming_up" y no un error."""

    @abstractmethod
    def warm_up(self) -> None:
        """Despierta la IA si hace falta; puede tardar, así que se llama en segundo plano."""
