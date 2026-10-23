from collections.abc import Generator

from sqlalchemy import URL, Engine, create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(database_url: str | URL) -> Engine:
    """Arma el engine sin conectarse (create_engine es perezoso)."""
    url = make_url(database_url)
    # values_plus_batch: los UPDATE van en bloque; un escaneo de campus sincroniza ~900 equipos de una vez. Solo existe
    # en psycopg2: las pruebas corren sobre SQLite (tests/conftest.py).
    postgres_options = {"executemany_mode": "values_plus_batch"} if url.get_backend_name() == "postgresql" else {}
    # pre_ping: el pooler de Supabase cierra conexiones inactivas y la primera petición fallaba.
    return create_engine(url, pool_pre_ping=True, **postgres_options)


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """Entrega una sesión por petición y siempre la cierra."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
