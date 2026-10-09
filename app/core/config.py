from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación, cargada desde las variables de entorno (.env)."""

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
