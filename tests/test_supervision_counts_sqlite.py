"""La supervisión del admin da los mismos hogares contando dispositivos y alertas en SQL que trayéndolos todos."""

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.device_presence import DEVICE_PRESENCE_TOLERANCE
from app.domain.device_role import DEVICE_ROLE_VALUES
from app.models.alert import Alert
from app.models.base import Base
from app.models.device import DEVICE_TRUST_VALUES, Device
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.role import Role
from app.models.user import User
from app.repositories.alert_repository import AlertRepository
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.repositories.security_assessment_sqlalchemy_repository import SqlAlchemySecurityAssessmentRepository
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.services.network_security_score_service import default_network_security_score_service
from app.services.network_supervision_service import NetworkSupervisionService

SCAN_AT = datetime(2026, 11, 4, 12, 0, 0, 500000, tzinfo=UTC)
OFFSETS = (timedelta(0), DEVICE_PRESENCE_TOLERANCE, DEVICE_PRESENCE_TOLERANCE * 2, timedelta(days=1))
HOUSEHOLDS = 6


class _LoadEverythingDeviceRepository(SqlAlchemyDeviceRepository):
    count_connected_members_by_owners = DeviceRepository.count_connected_members_by_owners


class _LoadEverythingAlertRepository(SqlAlchemyAlertRepository):
    count_unacknowledged_by_owners = AlertRepository.count_unacknowledged_by_owners


def _seed(db) -> None:
    rng = random.Random(7)
    db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
    db.add(User(id=uuid.uuid4(), email="admin@example.com", role_id=2))
    for number in range(HOUSEHOLDS):
        owner_id = uuid.uuid4()
        db.add(User(id=owner_id, email=f"home{number}@example.com", role_id=1))
        # El último hogar no tiene dispositivos, ni alertas, ni mediciones.
        if number == HOUSEHOLDS - 1:
            continue
        db.add_all(
            Device(
                owner_id=owner_id,
                name="",
                mac_address=f"aa-bb-cc-dd-{number:02x}-{index:02x}",
                ip_address=f"10.{number}.0.{index}",
                trust=rng.choice(DEVICE_TRUST_VALUES),
                network_role=rng.choice((None, *DEVICE_ROLE_VALUES)),
                first_seen=SCAN_AT,
                last_seen=SCAN_AT - rng.choice(OFFSETS),
            )
            for index in range(rng.randint(1, 120))
        )
        db.add_all(
            Alert(
                owner_id=owner_id,
                type="outage",
                severity="warning",
                message_key="user.alertsCenter.briefOutage",
                acknowledged=rng.random() < 0.5,
            )
            for _ in range(rng.randint(0, 40))
        )
        db.add(
            NetworkMetricSnapshot(
                owner_id=owner_id,
                latency_ms=20 + number * 40,
                jitter_ms=2,
                packet_loss_percent=0,
                status=("good", "warning", "critical")[number % 3],
                source="native",
            )
        )
    db.commit()


def _households(db, device_repository, alert_repository) -> list:
    return NetworkSupervisionService(
        user_repository=SqlAlchemyUserRepository(db),
        device_repository=device_repository,
        alert_repository=alert_repository,
        network_metrics_repository=SqlAlchemyNetworkMetricsRepository(db),
        security_assessment_repository=SqlAlchemySecurityAssessmentRepository(db),
        security_score_service=default_network_security_score_service(),
    ).list_households()


def test_counting_in_sql_gives_the_same_households_without_loading_devices_or_alerts() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        _seed(db)

    with session_factory() as db:
        before = _households(db, _LoadEverythingDeviceRepository(db), _LoadEverythingAlertRepository(db))

    loaded: list[object] = []

    def capture_loaded(_session, instance) -> None:
        if isinstance(instance, Device | Alert):
            loaded.append(instance)

    event.listen(session_factory, "loaded_as_persistent", capture_loaded)
    try:
        with session_factory() as db:
            after = _households(db, SqlAlchemyDeviceRepository(db), SqlAlchemyAlertRepository(db))
    finally:
        event.remove(session_factory, "loaded_as_persistent", capture_loaded)
        Base.metadata.drop_all(engine)

    assert len(after) == HOUSEHOLDS
    assert after == before
    assert len({household.security_score for household in after}) > 1
    assert loaded == []
