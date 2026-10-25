"""Único lugar donde el backend construye la IA; AI_MODE decide si corre aquí (paquete) o en el servicio aparte."""

from collections.abc import Callable
from datetime import timedelta
from functools import lru_cache

from fastapi import Depends
from redsana_ai import (
    AnomalyDetector,
    ChatEngine,
    GroqClient,
    IsolationForestAnomalyDetector,
    OutageDetector,
    StreakOutageDetector,
)
from sqlalchemy.orm import Session

from app.ai_gateway.ai_gateway import AiGateway
from app.ai_gateway.ai_service_client import AiServiceClient
from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.local_ai_gateway import LocalAiGateway
from app.ai_gateway.remote_ai_gateway import RemoteAiGateway
from app.ai_gateway.warm_up_controller import WarmUpSchedule
from app.core.config import get_settings
from app.domain.user_timezone import timezone_from_browser_offset
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.repositories.security_assessment_sqlalchemy_repository import SqlAlchemySecurityAssessmentRepository
from app.services.network_security_score_service import default_network_security_score_service
from app.services.security_assessment_service import SecurityAssessmentService
from app.services.security_assistant_service import SecurityAssistantService
from app.services.security_chat_context_service import SecurityChatContextBuilder


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


def build_local_anomaly_detector() -> AnomalyDetector:
    settings = get_settings()
    return IsolationForestAnomalyDetector(
        contamination=settings.anomaly_contamination,
        random_state=settings.anomaly_random_state,
        critical_z_score=settings.anomaly_critical_z_score,
    )


def build_local_outage_detector() -> OutageDetector:
    settings = get_settings()
    return StreakOutageDetector(
        packet_loss_threshold_percent=settings.outage_packet_loss_threshold_percent,
        max_gap_between_samples=timedelta(minutes=settings.outage_max_gap_minutes),
        critical_duration_minutes=settings.outage_critical_duration_minutes,
    )


def _local_ai_gateway(chat_engine_factory: Callable[[], ChatEngine]) -> LocalAiGateway:
    return LocalAiGateway(chat_engine_factory, build_local_anomaly_detector, build_local_outage_detector)


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
        local_fallback=_local_ai_gateway(get_chat_engine),
        usage_window=InteractiveUsageWindow(settings.ai_service_interactive_window_seconds),
        status_timeout_seconds=settings.ai_service_status_timeout_seconds,
        status_cache_seconds=settings.ai_service_status_cache_seconds,
        warm_up_schedule=WarmUpSchedule(
            timeout_seconds=settings.ai_service_warm_up_timeout_seconds,
            probe_timeout_seconds=settings.ai_service_warm_up_probe_timeout_seconds,
            backoff_seconds=settings.ai_service_warm_up_backoff_seconds,
            max_backoff_seconds=settings.ai_service_warm_up_max_backoff_seconds,
            backoff_factor=settings.ai_service_warm_up_backoff_factor,
            rate_limited_backoff_seconds=settings.ai_service_warm_up_rate_limited_backoff_seconds,
        ),
    )


def get_ai_gateway(engine: ChatEngine = Depends(get_chat_engine)) -> AiGateway:
    """Dependencia de los routers; en modo local usa el motor de get_chat_engine para que las pruebas lo reemplacen."""
    if get_settings().ai_mode == "remote":
        return _remote_ai_gateway()
    return _local_ai_gateway(lambda: engine)


def build_ai_gateway() -> AiGateway:
    """Para código fuera de una petición (tareas en segundo plano), donde no hay inyección de dependencias."""
    if get_settings().ai_mode == "remote":
        return _remote_ai_gateway()
    return _local_ai_gateway(get_chat_engine)


def build_anomaly_detector() -> AnomalyDetector:
    return build_ai_gateway().anomaly_detector()


def build_outage_detector() -> OutageDetector:
    return build_ai_gateway().outage_detector()


def build_security_assessment_service(db: Session) -> SecurityAssessmentService:
    return SecurityAssessmentService(
        SqlAlchemySecurityAssessmentRepository(db), default_network_security_score_service()
    )


def build_security_assistant(gateway: AiGateway, db: Session, utc_offset_minutes: int) -> SecurityAssistantService:
    """El asistente del chat: la IA del gateway más el contexto de la red del usuario, con las horas en su zona."""
    return SecurityAssistantService(
        gateway.security_chat(),
        gateway.security_briefing(),
        SecurityChatContextBuilder(
            device_repository=SqlAlchemyDeviceRepository(db),
            alert_repository=SqlAlchemyAlertRepository(db),
            network_metrics_repository=SqlAlchemyNetworkMetricsRepository(db),
            security_assessment_service=build_security_assessment_service(db),
            user_timezone=timezone_from_browser_offset(utc_offset_minutes),
        ),
    )
