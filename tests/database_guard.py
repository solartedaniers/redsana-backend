"""Guarda de las pruebas: ninguna corrida de pytest puede usar la base real (el .env apunta a Supabase de producción)."""
import pytest
from sqlalchemy import URL, make_url

# En memoria: cada prueba que necesita tablas arma su propio engine; la app, sin override, no encuentra ninguna.
TEST_DATABASE_URL = "sqlite://"
# Dominio .invalid: nunca resuelve, así que ninguna prueba puede llamar por error a Supabase Auth ni al JWKS real.
TEST_SUPABASE_URL = "https://supabase.invalid"
TEST_SUPABASE_SERVICE_ROLE_KEY = "test-service-role-key"
# IA en el proceso y sin claves: una prueba que olvide su stub falla aquí en vez de llamar a Groq o a la IA desplegada.
TEST_AI_ENVIRONMENT = {
    "AI_MODE": "local",
    "AI_SERVICE_URL": "",
    "AI_SERVICE_API_KEY": "",
    "GROQ_API_KEY": "test-groq-key",
    "GROQ_API_URL": "https://groq.invalid/openai/v1/chat/completions",
}
ABORT_RETURN_CODE = 3


def abort_unless_test_database(url: str | URL) -> None:
    """Corta toda la sesión de pytest si la base efectiva no es SQLite (sin conectarse a ella para comprobarlo)."""
    if make_url(url).get_backend_name() != "sqlite":
        pytest.exit(
            f"Pruebas abortadas: la base efectiva es '{make_url(url).get_backend_name()}', no SQLite. "
            "Las pruebas nunca deben tocar la base real.",
            returncode=ABORT_RETURN_CODE,
        )
