from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# pre_ping: el pooler de Supabase cierra conexiones inactivas y la primera petición fallaba.
# values_plus_batch: los UPDATE van en bloque; un escaneo de campus sincroniza ~900 equipos de una vez.
engine = create_engine(get_settings().database_url, pool_pre_ping=True, executemany_mode="values_plus_batch")
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """Entrega una sesión por petición y siempre la cierra."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
