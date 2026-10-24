"""Ventana de los avisos de degradación con el repositorio real en SQLite y el PATCH de marcar como visto."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redsana_ai import ANOMALY_WINDOW_SIZE, IsolationForestAnomalyDetector
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.base import Base
from app.models.role import Role
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.services.network_anomaly_service import NetworkAnomalyService
from tests.test_network_anomaly_service import HOME_NETWORK, _seed_normal_history
from tests.test_network_metrics_service import FakeNetworkMetricsRepository

OWNER_ID = uuid.uuid4()
COOLDOWN = timedelta(minutes=60)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
        db.commit()
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)


def _evaluate_anomaly(alert_repository: SqlAlchemyAlertRepository) -> None:
    metrics_repository = FakeNetworkMetricsRepository()
    _seed_normal_history(metrics_repository, OWNER_ID, ANOMALY_WINDOW_SIZE - 1)
    metrics_repository.create(
        owner_id=OWNER_ID,
        latency_ms=400.0,
        jitter_ms=2.0,
        packet_loss_percent=0.0,
        status="critical",
        source="native",
        network_id=HOME_NETWORK,
        recorded_at=None,
    )
    NetworkAnomalyService(
        metrics_repository, alert_repository, IsolationForestAnomalyDetector(), alert_cooldown=COOLDOWN
    ).evaluate_latest(OWNER_ID)


def _previous_alert(repository: SqlAlchemyAlertRepository, age: timedelta):
    return repository.create(
        owner_id=OWNER_ID,
        type_="prediction",
        severity="critical",
        message_key="user.alertsCenter.messages.latencyDegraded",
        message_params=None,
        created_at=datetime.now(UTC) - age,
    )


def test_within_the_window_sqlite_does_not_repeat(session_factory) -> None:
    with session_factory() as db:
        repository = SqlAlchemyAlertRepository(db)
        _previous_alert(repository, timedelta(minutes=5))

        _evaluate_anomaly(repository)

        assert len(repository.list_all(OWNER_ID)) == 1


def test_outside_the_window_sqlite_repeats(session_factory) -> None:
    with session_factory() as db:
        repository = SqlAlchemyAlertRepository(db)
        _previous_alert(repository, COOLDOWN + timedelta(minutes=5))

        _evaluate_anomaly(repository)

        assert len(repository.list_all(OWNER_ID)) == 2


def test_marking_as_seen_still_works_and_only_the_window_decides(session_factory) -> None:
    with session_factory() as db:
        alert_id = _previous_alert(SqlAlchemyAlertRepository(db), COOLDOWN + timedelta(minutes=5)).id

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: {"sub": str(OWNER_ID), "email": "owner@example.com"}
    try:
        response = TestClient(app).patch(f"/api/alerts/{alert_id}/acknowledge")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["acknowledged"] is True
    with session_factory() as db:
        repository = SqlAlchemyAlertRepository(db)
        _evaluate_anomaly(repository)
        alerts = repository.list_all(OWNER_ID)
        assert len(alerts) == 2
        assert sorted(alert.acknowledged for alert in alerts) == [False, True]
