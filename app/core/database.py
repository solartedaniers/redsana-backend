from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# pre_ping: el pooler de Supabase cierra conexiones inactivas; sin esto, la
# primera peticion tras un rato sin trafico falla con "server closed the connection".
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """Dependency de FastAPI: entrega una sesion por request y siempre la cierra."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
