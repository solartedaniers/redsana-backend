from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracion de la aplicacion, cargada desde variables de entorno (.env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    supabase_url: str
    supabase_jwt_audience: str = "authenticated"
    jwks_cache_ttl_seconds: int = 3600
    cors_origins: str = ""
    network_metrics_default_history_hours: int = 24
    supabase_service_role_key: str
    groq_api_key: str
    groq_model: str = "openai/gpt-oss-120b"
    # Secreto del HMAC que convierte la huella de red del escritorio en network_id
    # (ver app.domain.network_identity). Debe ser el mismo en todo backend que
    # comparta base de datos: si cambia, cada red vuelve a calibrar desde cero.
    network_id_secret: str
    groq_timeout_seconds: int = 30
    # Timeout de las llamadas a Supabase (JWKS y Admin API): los endpoints son
    # síncronos y corren en el pool de hilos; sin timeout, un Supabase colgado
    # deja cada hilo bloqueado para siempre hasta agotar el pool.
    supabase_http_timeout_seconds: int = 10
    # Baja a propósito: el asistente copia datos exactos (DNS, puertos) y una
    # temperatura alta lo hacía variar dígitos (llegó a escribir 0.0.0.3 por 1.0.0.3).
    groq_temperature: float = 0.2

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def cors_origins_list(self) -> list[str]:
        # env var como lista separada por comas (mas simple que exigir JSON en el .env)
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    # cacheada porque Settings() relee y parsea el .env en cada instanciacion
    return Settings()
