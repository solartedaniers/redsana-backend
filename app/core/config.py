from datetime import timedelta
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.measurement_source import MeasurementSource
from app.domain.measurement_timing import MeasurementTimingPolicy
from app.domain.network_status import NetworkStatusThresholds
from app.domain.security_score_config import SecurityScoreConfig


class Settings(BaseSettings):
    """Configuración de la aplicación, cargada desde las variables de entorno (.env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    supabase_url: str
    supabase_jwt_audience: str = "authenticated"
    jwks_cache_ttl_seconds: int = 3600
    # Un kid desconocido refresca el JWKS (rotación de claves) como mucho una vez por este intervalo: un token con un kid
    # inventado no puede hacer que cada petición consulte a Supabase.
    jwks_unknown_kid_refresh_seconds: int = 60
    cors_origins: str = ""
    network_metrics_default_history_hours: int = 24
    # Umbrales del estado de cada medición (advertencia / crítica). Cambiarlos solo afecta a las mediciones nuevas: el
    # estado se guarda al registrar cada una y las viejas no se recalculan.
    network_status_latency_warning_ms: float = 80
    network_status_latency_critical_ms: float = 150
    network_status_packet_loss_warning_percent: float = 1
    network_status_packet_loss_critical_percent: float = 5
    # La web mide un fetch hasta el servidor (normal ~170–290 ms), no un ping a la red de la casa: necesita su propia
    # escala de latencia. La pérdida de paquetes usa los mismos umbrales en las dos fuentes.
    network_status_web_latency_warning_ms: float = 400
    network_status_web_latency_critical_ms: float = 800
    # Tras un aviso de degradación no se crea otro igual durante este tiempo, aunque el primero ya se haya marcado
    # como visto: si no, saldría uno por minuto mientras dure el problema.
    prediction_alert_cooldown_minutes: int = 60
    # Hora de medición que manda el cliente (cola local): se rechaza si es más vieja que esto o está en el futuro más
    # allá del margen por relojes desfasados.
    measurement_max_age_hours: int = 24
    measurement_max_future_seconds: int = 300
    # Una medición que llega con más de este retraso ya pasó: registra cortes, pero no dispara avisos de degradación.
    measurement_late_after_seconds: int = 180
    # Puntaje de seguridad: desde dónde es bueno o regular, y cuánto pesa cada parte (suman 100).
    security_score_good_min: int = 80
    security_score_warning_min: int = 50
    security_score_questionnaire_weight_percent: int = 30
    security_score_technical_weight_percent: int = 70
    supabase_service_role_key: str
    # Solo la exige el modo local (ver _require_ai_mode_settings); en modo remoto Groq vive en el servicio de IA.
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_api_url: str = "https://api.groq.com/openai/v1/chat/completions"
    # Secreto del HMAC que convierte la huella de red en network_id; si cambia, cada red vuelve a calibrar
    # desde cero, así que debe ser el mismo en todo backend que comparta la base.
    network_id_secret: str
    groq_timeout_seconds: int = 30
    # Sin timeout, un Supabase colgado dejaría bloqueado cada hilo del pool hasta agotarlo.
    supabase_http_timeout_seconds: int = 10
    # Baja a propósito: con temperatura alta el asistente cambiaba dígitos al copiar DNS (llegó a escribir 0.0.0.3).
    groq_temperature: float = 0.2
    # Apagado por defecto: el endpoint de alertas de prueba solo debe existir en desarrollo.
    enable_test_alerts_endpoint: bool = False
    # local usa el paquete redsana_ai en este proceso; remote llama al servicio de IA. Local por defecto para que
    # subir código no cambie producción hasta que se cambie esta variable.
    ai_mode: Literal["local", "remote"] = "local"
    ai_service_url: str = ""
    ai_service_api_key: str = ""
    # Mayor que groq_timeout_seconds del servicio: si no, cortaría respuestas que Groq sí iba a dar.
    ai_service_timeout_seconds: float = 45.0
    # Corto a propósito: una consulta suelta de estado (fuera del calentamiento) no debe frenar al usuario.
    ai_service_status_timeout_seconds: float = 5.0
    # Cuánto vale el último estado conocido sin volver a consultar al servicio: /api/ai/status lee la memoria.
    ai_service_status_cache_seconds: float = 5.0
    # Plazo total del calentamiento en segundo plano: el arranque en frío en Render incluye importar scikit-learn y
    # se midió en ~43 s solo para la IA; con varios minutos sobra margen. Vencido, la IA queda "no disponible".
    ai_service_warm_up_timeout_seconds: float = 300.0
    # Cada consulta del calentamiento queda abierta este tiempo, como el navegador: Render la retiene mientras despierta.
    ai_service_warm_up_probe_timeout_seconds: float = 90.0
    # Si una consulta falla (429/50x/sin conexión), la siguiente espera esto y crece por el factor hasta el tope.
    ai_service_warm_up_backoff_seconds: float = 5.0
    ai_service_warm_up_max_backoff_seconds: float = 15.0
    ai_service_warm_up_backoff_factor: float = 1.5
    # Ante un 429 de Render con x-render-routing=hibernate-rate-limited espero al menos esto: insistir lo empeora.
    ai_service_warm_up_rate_limited_backoff_seconds: float = 30.0
    # Retry-After que el chat devuelve al frontend cuando la IA aún está encendiendo.
    ai_service_warm_up_poll_seconds: float = 2.0
    ai_service_max_retries: int = 2
    ai_service_retry_backoff_seconds: float = 1.0
    # Tras el último uso interactivo (calentamiento, chat o resumen), cuánto tiempo los detectores en segundo plano
    # siguen usando el servicio; fuera de la ventana usan el paquete local para no despertarlo con cada medición.
    ai_service_interactive_window_seconds: int = 600

    @model_validator(mode="after")
    def _require_ai_mode_settings(self) -> "Settings":
        if self.ai_mode == "local" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when AI_MODE=local")
        if self.ai_mode == "remote" and not (self.ai_service_url and self.ai_service_api_key):
            raise ValueError("AI_SERVICE_URL and AI_SERVICE_API_KEY are required when AI_MODE=remote")
        return self

    @model_validator(mode="after")
    def _require_ordered_network_status_thresholds(self) -> "Settings":
        thresholds = self.network_status_thresholds
        if not 0 < thresholds.latency_warning_ms <= thresholds.latency_critical_ms:
            raise ValueError("NETWORK_STATUS_LATENCY_WARNING_MS must be > 0 and <= NETWORK_STATUS_LATENCY_CRITICAL_MS")
        if not 0 < self.network_status_web_latency_warning_ms <= self.network_status_web_latency_critical_ms:
            raise ValueError(
                "NETWORK_STATUS_WEB_LATENCY_WARNING_MS must be > 0 and <= NETWORK_STATUS_WEB_LATENCY_CRITICAL_MS"
            )
        if not 0 < thresholds.packet_loss_warning_percent <= thresholds.packet_loss_critical_percent <= 100:
            raise ValueError(
                "NETWORK_STATUS_PACKET_LOSS_WARNING_PERCENT must be > 0 and <= "
                "NETWORK_STATUS_PACKET_LOSS_CRITICAL_PERCENT, which must be <= 100"
            )
        return self

    @model_validator(mode="after")
    def _require_coherent_security_score_config(self) -> "Settings":
        config = self.security_score_config
        if not 0 < config.warning_min <= config.good_min <= 100:
            raise ValueError(
                "SECURITY_SCORE_WARNING_MIN must be > 0 and <= SECURITY_SCORE_GOOD_MIN, which must be <= 100"
            )
        weights = (config.questionnaire_weight_percent, config.technical_weight_percent)
        if min(weights) < 0 or sum(weights) != 100:
            raise ValueError(
                "SECURITY_SCORE_QUESTIONNAIRE_WEIGHT_PERCENT and SECURITY_SCORE_TECHNICAL_WEIGHT_PERCENT must be >= 0 "
                "and add up to 100"
            )
        return self

    @property
    def network_status_thresholds(self) -> NetworkStatusThresholds:
        return NetworkStatusThresholds(
            latency_warning_ms=self.network_status_latency_warning_ms,
            latency_critical_ms=self.network_status_latency_critical_ms,
            packet_loss_warning_percent=self.network_status_packet_loss_warning_percent,
            packet_loss_critical_percent=self.network_status_packet_loss_critical_percent,
        )

    def network_status_thresholds_for(self, source: MeasurementSource) -> NetworkStatusThresholds:
        """Única fuente de los umbrales por fuente: el estado guardado, GET /thresholds y el asistente leen de aquí."""
        if source == "native":
            return self.network_status_thresholds
        return NetworkStatusThresholds(
            latency_warning_ms=self.network_status_web_latency_warning_ms,
            latency_critical_ms=self.network_status_web_latency_critical_ms,
            packet_loss_warning_percent=self.network_status_packet_loss_warning_percent,
            packet_loss_critical_percent=self.network_status_packet_loss_critical_percent,
        )

    @property
    def measurement_timing_policy(self) -> MeasurementTimingPolicy:
        return MeasurementTimingPolicy(
            max_age=timedelta(hours=self.measurement_max_age_hours),
            max_future=timedelta(seconds=self.measurement_max_future_seconds),
            late_after=timedelta(seconds=self.measurement_late_after_seconds),
        )

    @property
    def security_score_config(self) -> SecurityScoreConfig:
        return SecurityScoreConfig(
            good_min=self.security_score_good_min,
            warning_min=self.security_score_warning_min,
            questionnaire_weight_percent=self.security_score_questionnaire_weight_percent,
            technical_weight_percent=self.security_score_technical_weight_percent,
        )

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def cors_origins_list(self) -> list[str]:
        # lista separada por comas, más simple que exigir JSON en el .env
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    # La cacheo porque Settings() vuelve a leer y parsear el .env cada vez.
    return Settings()
