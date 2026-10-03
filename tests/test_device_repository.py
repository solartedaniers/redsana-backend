"""Repositorio real sobre SQLite en memoria: last_seen solo debe moverse cuando
un escaneo ve el dispositivo, no al editar otros campos (p. ej. la confianza)."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository


def test_changing_trust_does_not_touch_last_seen() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        repository = SqlAlchemyDeviceRepository(db)
        owner_id = uuid.uuid4()
        scanned_at = datetime.now(timezone.utc) - timedelta(days=10)
        device = repository.create(
            owner_id=owner_id, name="", mac_address="aa-bb-cc-dd-ee-ff", ip_address="192.168.1.5",
            trust="unknown", last_seen=scanned_at,
        )

        updated = repository.update(device.id, owner_id, {"trust": "trusted"})

        assert updated.last_seen.replace(tzinfo=timezone.utc) == scanned_at
