"""Único lugar donde el backend construye la IA; AI_MODE decide si corre aquí (paquete) o en el servicio aparte."""
from functools import lru_cache

from fastapi import Depends
from redsana_ai import AnomalyDetector, ChatEngine, GroqClient, OutageDetector

from app.ai_gateway.ai_gateway import AiGateway
from app.ai_gateway.ai_service_client import AiServiceClient
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.local_ai_gateway import LocalAiGateway
from app.ai_gateway.remote_ai_gateway import RemoteAiGateway
from app.core.config import get_settings


def get_chat_engine() -> ChatEngine:
    # Va como dependencia aparte para poder reemplazarla en las pruebas sin llamar a la API real de Groq.
    settings = get_settings()
    return GroqClient(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        timeout_seconds=settings.groq_timeout_seconds,
        temperature=settings.groq_temperature,
        api_url=settings.groq_api_url,
    )


@lru_cache
def _remote_ai_gateway() -> RemoteAiGateway:
    # Uno solo por proceso: la ventana de uso interactivo debe ser la misma para todas las peticiones.
    settings = get_settings()

    def client(max_retries: int) -> AiServiceClient:
        return AiServiceClient(
            base_url=settings.ai_service_url,
            api_key=settings.ai_service_api_key,
            timeout_seconds=settings.ai_service_timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=settings.ai_service_retry_backoff_seconds,
        )

    return RemoteAiGateway(
        client=client(settings.ai_service_max_retries),
        status_client=client(max_retries=0),
        local_fallback=LocalAiGateway(get_chat_engine),
        usage_window=InteractiveUsageWindow(settings.ai_service_interactive_window_seconds),
        status_timeout_seconds=settings.ai_service_status_timeout_seconds,
        warm_up_timeout_seconds=settings.ai_service_warm_up_timeout_seconds,
        warm_up_probe_timeout_seconds=settings.ai_service_warm_up_probe_timeout_seconds,
        warm_up_poll_seconds=settings.ai_service_warm_up_poll_seconds,
    )


def get_ai_gateway(engine: ChatEngine = Depends(get_chat_engine)) -> AiGateway:
    """Dependencia de los routers; en modo local usa el motor de get_chat_engine para que las pruebas lo reemplacen."""
    if get_settings().ai_mode == "remote":
        return _remote_ai_gateway()
    return LocalAiGateway(lambda: engine)


def build_ai_gateway() -> AiGateway:
    """Para código fuera de una petición (tareas en segundo plano), donde no hay inyección de dependencias."""
    if get_settings().ai_mode == "remote":
        return _remote_ai_gateway()
    return LocalAiGateway(get_chat_engine)


def build_anomaly_detector() -> AnomalyDetector:
    return build_ai_gateway().anomaly_detector()


def build_outage_detector() -> OutageDetector:
    return build_ai_gateway().outage_detector()
