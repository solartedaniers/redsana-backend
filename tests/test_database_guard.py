"""La guarda de tests/conftest.py: la app de las pruebas usa SQLite y un intento de usar la base real falla."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql.psycopg2 import EXECUTEMANY_VALUES_PLUS_BATCH
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.database import SessionLocal, build_engine, engine
from app.core.security import get_current_claims
from app.main import app
from tests.database_guard import ABORT_RETURN_CODE, abort_unless_test_database

REAL_LOOKING_URL = "postgresql://postgres:secreto@db.ejemplo.supabase.co:5432/postgres"


def test_the_app_engine_and_settings_are_sqlite_during_tests() -> None:
    assert engine.url.get_backend_name() == "sqlite"
    assert get_settings().database_url.startswith("sqlite")
    with SessionLocal() as db:
        assert db.get_bind().url.get_backend_name() == "sqlite"


def test_the_guard_aborts_the_whole_session_for_a_postgres_url_without_connecting() -> None:
    with pytest.raises(pytest.exit.Exception) as aborted:
        abort_unless_test_database(REAL_LOOKING_URL)

    assert aborted.value.returncode == ABORT_RETURN_CODE


def test_the_guard_accepts_sqlite() -> None:
    abort_unless_test_database("sqlite://")
    abort_unless_test_database("sqlite:///:memory:")


def test_production_postgres_keeps_values_plus_batch_without_connecting() -> None:
    """Solo arma la configuración: el host .invalid no resuelve y create_engine no abre conexión."""
    postgres = build_engine(REAL_LOOKING_URL.replace("db.ejemplo.supabase.co", "db.invalid"))

    assert postgres.dialect.driver == "psycopg2"
    assert postgres.dialect.executemany_mode == EXECUTEMANY_VALUES_PLUS_BATCH
    assert postgres.pool.checkedout() == 0


def test_sqlite_gets_no_postgres_only_options() -> None:
    assert not hasattr(build_engine("sqlite://").dialect, "executemany_mode")


def test_a_test_that_forgets_the_db_override_fails_locally_instead_of_writing_anywhere() -> None:
    """Lo que pasó con test_me_router: sin override de get_db la app usaba el .env real; ahora no hay tablas."""
    app.dependency_overrides[get_current_claims] = lambda: {"sub": str(uuid.uuid4()), "email": "guard@example.com"}
    try:
        with pytest.raises(OperationalError, match="no such table"):
            TestClient(app).get("/api/users/me")
    finally:
        app.dependency_overrides.clear()
