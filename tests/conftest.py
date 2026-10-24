"""Se carga antes que cualquier módulo de pruebas: fija la base en SQLite antes de importar la app y aborta si no lo es."""

import os

from tests.database_guard import (
    TEST_AI_ENVIRONMENT,
    TEST_DATABASE_URL,
    TEST_SUPABASE_SERVICE_ROLE_KEY,
    TEST_SUPABASE_URL,
    abort_unless_test_database,
)

# Las variables de entorno mandan sobre el .env en pydantic-settings: así el .env de producción no llega a las pruebas.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SUPABASE_URL"] = TEST_SUPABASE_URL
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = TEST_SUPABASE_SERVICE_ROLE_KEY
os.environ.update(TEST_AI_ENVIRONMENT)

from app.core.database import engine  # noqa: E402  (tiene que ir después de fijar el entorno)

abort_unless_test_database(engine.url)
