"""Cola local del cliente con la app real y SQLite: hora original validada, reenvíos sin duplicados y mediciones
tardías que registran el corte pero no disparan avisos de degradación."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_claims
from app.main import app
from app.models.alert import Alert
from app.models.base import Base
from app.models.network_metric_snapshot import NetworkMetricSnapshot
from app.models.role import Role

OWNER_ID = uuid.uuid4()
NORMAL = {"latency_ms": 200, "jitter_ms": 5, "packet_loss_percent": 0, "source": "web"}
CUT = {"latency_ms": 0, "jitter_ms": 0, "packet_loss_percent": 100, "source": "web"}


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as db:
        db.add_all([Role(id=1, name="standard"), Role(id=2, name="admin")])
        db.commit()
    # Las tareas en segundo plano abren su propia sesión: también van a la base de prueba.
    monkeypatch.setattr("app.routers.network_metrics.SessionLocal", session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_claims] = lambda: {"sub": str(OWNER_ID), "email": "owner@example.com"}
    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _at(minutes_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def _count(session_factory, model) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def _alerts(session_factory, type_: str) -> list[Alert]:
    with session_factory() as db:
        return list(db.scalars(select(Alert).where(Alert.type == type_)).all())


def test_replaying_the_same_measurement_twice_stores_it_once(env) -> None:
    client, session_factory = env
    payload = {**NORMAL, "recorded_at": _at(30)}

    first = client.post("/api/network-metrics", json=payload)
    second = client.post("/api/network-metrics", json=payload)

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json() == second.json()
    assert _count(session_factory, NetworkMetricSnapshot) == 1


def test_replaying_a_whole_queue_twice_does_not_duplicate_anything(env) -> None:
    client, session_factory = env
    queue = [{**NORMAL, "recorded_at": _at(m)} for m in (12, 11, 10)]

    for _ in range(2):
        for payload in queue:
            assert client.post("/api/network-metrics", json=payload).status_code == 201

    assert _count(session_factory, NetworkMetricSnapshot) == 3


def test_without_recorded_at_every_post_is_a_new_measurement_as_before(env) -> None:
    client, session_factory = env
    payload = {"latency_ms": 20, "jitter_ms": 2, "packet_loss_percent": 0}  # como el instalador 0.1.5

    client.post("/api/network-metrics", json=payload)
    client.post("/api/network-metrics", json=payload)

    assert _count(session_factory, NetworkMetricSnapshot) == 2


def test_the_same_time_from_another_source_is_another_measurement(env) -> None:
    client, session_factory = env
    recorded_at = _at(5)

    client.post("/api/network-metrics", json={**NORMAL, "recorded_at": recorded_at})
    client.post("/api/network-metrics", json={**NORMAL, "source": "native", "recorded_at": recorded_at})

    assert _count(session_factory, NetworkMetricSnapshot) == 2


def test_the_original_time_is_kept(env) -> None:
    client, _ = env
    recorded_at = datetime.now(UTC) - timedelta(hours=3)

    response = client.post("/api/network-metrics", json={**NORMAL, "recorded_at": recorded_at.isoformat()})

    assert datetime.fromisoformat(response.json()["updated_at"]).replace(tzinfo=UTC) == recorded_at


@pytest.mark.parametrize("minutes_ahead", [10, 60 * 24])
def test_a_time_in_the_future_is_rejected(env, minutes_ahead: int) -> None:
    client, session_factory = env

    response = client.post("/api/network-metrics", json={**NORMAL, "recorded_at": _at(-minutes_ahead)})

    assert response.status_code == 422
    assert _count(session_factory, NetworkMetricSnapshot) == 0


def test_a_clock_slightly_ahead_is_accepted(env) -> None:
    client, _ = env

    assert client.post("/api/network-metrics", json={**NORMAL, "recorded_at": _at(-1)}).status_code == 201


def test_a_time_older_than_the_limit_is_rejected(env) -> None:
    client, _ = env

    response = client.post("/api/network-metrics", json={**NORMAL, "recorded_at": _at(60 * 25)})

    assert response.status_code == 422


def test_the_age_limit_comes_from_the_environment(env, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = env
    monkeypatch.setenv("MEASUREMENT_MAX_AGE_HOURS", "1")
    get_settings.cache_clear()
    try:
        response = client.post("/api/network-metrics", json={**NORMAL, "recorded_at": _at(90)})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 422


def test_a_late_outage_is_recorded_once_with_its_real_duration(env) -> None:
    client, session_factory = env
    # Lo que la cola reenvía al volver la conexión, en orden: antes, durante y al salir del corte.
    queue = [
        {**NORMAL, "recorded_at": _at(21)},
        *({**CUT, "recorded_at": _at(m)} for m in (20, 19, 18, 17, 16, 15, 14, 13)),
        {**NORMAL, "recorded_at": _at(12)},
    ]

    for payload in queue:
        client.post("/api/network-metrics", json=payload)
    for payload in queue:  # un segundo reenvío completo no crea otra alerta
        client.post("/api/network-metrics", json=payload)

    outages = _alerts(session_factory, "outage")
    assert len(outages) == 1
    assert outages[0].message_params == {"minutes": 8}


def _seed_calibrated_web_history(session_factory) -> None:
    """Historial web normal y suficiente para que el detector de anomalías esté activo."""
    required = get_settings().anomaly_min_samples_for("web")
    start = datetime.now(UTC) - timedelta(minutes=required + 60)
    with session_factory() as db:
        db.add_all(
            NetworkMetricSnapshot(
                owner_id=OWNER_ID,
                latency_ms=200 + (i % 5) * 2,
                jitter_ms=5 + (i % 3) * 0.2,
                packet_loss_percent=0,
                status="good",
                source="web",
                network_id=None,
                recorded_at=start + timedelta(minutes=i),
            )
            for i in range(required)
        )
        db.commit()


def _first_post_creates_the_owner(client: TestClient) -> None:
    # get_current_user crea el usuario en su primer request; el historial sembrado necesita que exista.
    client.get("/api/network-metrics/latest")


def test_a_late_degraded_measurement_does_not_raise_a_degradation_alert_now(env) -> None:
    client, session_factory = env
    _first_post_creates_the_owner(client)
    _seed_calibrated_web_history(session_factory)

    client.post("/api/network-metrics", json={**NORMAL, "latency_ms": 3000, "recorded_at": _at(10)})

    assert _alerts(session_factory, "prediction") == []


def test_the_same_degraded_measurement_in_real_time_does_raise_it(env) -> None:
    # Control de la prueba anterior: el detector sí lo marca cuando la medición es actual.
    client, session_factory = env
    _first_post_creates_the_owner(client)
    _seed_calibrated_web_history(session_factory)

    client.post("/api/network-metrics", json={**NORMAL, "latency_ms": 3000, "recorded_at": _at(0)})

    assert len(_alerts(session_factory, "prediction")) == 1


# Reloj del PC mal puesto: el cliente manda sent_at (su hora al enviar) y el backend corrige recorded_at.
SKEWED_CLOCKS = [pytest.param(10, id="adelantado-10-min"), pytest.param(-10, id="atrasado-10-min")]


class _SkewedClient:
    """Cliente cuyo reloj va `skew_minutes` adelantado (o atrasado): su cola guarda la hora de su propio reloj y pone
    sent_at al enviar, como la cola del escritorio."""

    def __init__(self, client: TestClient, skew_minutes: int) -> None:
        self._client = client
        self._skew = timedelta(minutes=skew_minutes)

    def _clock(self) -> datetime:
        return datetime.now(UTC) + self._skew

    def measure(self, payload: dict, minutes_ago: float) -> dict:
        return {**payload, "recorded_at": (self._clock() - timedelta(minutes=minutes_ago)).isoformat()}

    def send(self, item: dict):
        return self._client.post("/api/network-metrics", json={**item, "sent_at": self._clock().isoformat()})


@pytest.mark.parametrize("skew_minutes", SKEWED_CLOCKS)
def test_a_wrong_pc_clock_loses_and_duplicates_nothing_and_records_the_outage(env, skew_minutes: int) -> None:
    client, session_factory = env
    pc = _SkewedClient(client, skew_minutes)
    queue = [
        pc.measure(NORMAL, 21),
        *(pc.measure(CUT, m) for m in (20, 19, 18, 17, 16, 15, 14, 13)),
        pc.measure(NORMAL, 12),
    ]

    for _ in range(2):  # el segundo reenvío completo no duplica nada
        for item in queue:
            assert pc.send(item).status_code == 201

    assert _count(session_factory, NetworkMetricSnapshot) == len(queue)
    outages = _alerts(session_factory, "outage")
    assert len(outages) == 1
    assert outages[0].message_params == {"minutes": 8}


@pytest.mark.parametrize("skew_minutes", SKEWED_CLOCKS)
def test_a_wrong_pc_clock_is_stored_at_the_real_time(env, skew_minutes: int) -> None:
    client, _ = env
    pc = _SkewedClient(client, skew_minutes)
    real_time = datetime.now(UTC) - timedelta(minutes=30)

    response = pc.send(pc.measure(NORMAL, 30))

    stored = datetime.fromisoformat(response.json()["updated_at"]).replace(tzinfo=UTC)
    assert abs(stored - real_time) < timedelta(seconds=5)


@pytest.mark.parametrize("skew_minutes", SKEWED_CLOCKS)
def test_a_wrong_pc_clock_still_raises_degradation_in_real_time(env, skew_minutes: int) -> None:
    client, session_factory = env
    _first_post_creates_the_owner(client)
    _seed_calibrated_web_history(session_factory)
    pc = _SkewedClient(client, skew_minutes)

    pc.send(pc.measure({**NORMAL, "latency_ms": 3000}, 0))

    assert len(_alerts(session_factory, "prediction")) == 1


@pytest.mark.parametrize("skew_minutes", SKEWED_CLOCKS)
def test_a_wrong_pc_clock_still_marks_a_late_degradation_as_late(env, skew_minutes: int) -> None:
    client, session_factory = env
    _first_post_creates_the_owner(client)
    _seed_calibrated_web_history(session_factory)
    pc = _SkewedClient(client, skew_minutes)

    pc.send(pc.measure({**NORMAL, "latency_ms": 3000}, 10))

    assert _alerts(session_factory, "prediction") == []


def test_a_measurement_taken_after_it_was_sent_is_rejected(env) -> None:
    client, _ = env
    now = datetime.now(UTC)

    response = client.post(
        "/api/network-metrics",
        json={**NORMAL, "recorded_at": (now + timedelta(minutes=10)).isoformat(), "sent_at": now.isoformat()},
    )

    assert response.status_code == 422


def test_a_measurement_older_than_the_limit_is_rejected_even_with_sent_at(env) -> None:
    client, _ = env
    pc = _SkewedClient(client, -10)

    assert pc.send(pc.measure(NORMAL, 60 * 25)).status_code == 422
