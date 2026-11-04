"""El estado de la IA en Redis (fakeredis): lo que sabe un worker lo leen los demás sin consultar al servicio, cada
cambio se avisa una sola vez y sin Redis (o con un valor roto) cada worker sigue con su estado en memoria."""

import uuid

import fakeredis

from app.ai_gateway.interactive_usage_window import InteractiveUsageWindow
from app.ai_gateway.local_ai_gateway import LocalAiGateway
from app.ai_gateway.remote_ai_gateway import RemoteAiGateway
from app.ai_gateway.shared_ai_status import AiStatusSnapshot, SharedAiStatus
from app.cache.cache_store import CacheStore, FailureCooldown, NullCacheStore, RedisCacheStore
from app.realtime.connections import ConnectionRegistry
from app.realtime.events import AI_STATUS_CHANGED, RealtimeEvent
from tests.test_remote_ai_gateway import _ASLEEP, _SCHEDULE, _FakeStatusClient, _FakeTime, _Threads

KEY = "test:ai-status"


def _redis_store(server: fakeredis.FakeServer) -> CacheStore:
    return RedisCacheStore(fakeredis.FakeRedis(server=server, decode_responses=True), FailureCooldown(30))


def _worker(
    status_client: _FakeStatusClient,
    store: CacheStore,
    changes: list[AiStatusSnapshot] | None = None,
    fake_time: _FakeTime | None = None,
    threads: _Threads | None = None,
) -> RemoteAiGateway:
    fake_time = fake_time or _FakeTime()
    return RemoteAiGateway(
        client=status_client,
        status_client=status_client,
        local_fallback=LocalAiGateway(lambda: None),
        usage_window=InteractiveUsageWindow(600, clock=fake_time.clock),
        status_timeout_seconds=5,
        status_cache_seconds=5,
        warm_up_schedule=_SCHEDULE,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        start_thread=(threads or _Threads()).start,
        shared_status=SharedAiStatus(store, KEY),
        on_status_change=changes.append if changes is not None else None,
    )


def test_what_one_worker_learns_the_other_reads_from_redis_without_asking_the_service() -> None:
    server = fakeredis.FakeServer()
    client_a, client_b = _FakeStatusClient(True), _FakeStatusClient(False)

    assert _worker(client_a, _redis_store(server)).status() == "ready"
    assert _worker(client_b, _redis_store(server)).status() == "ready"
    assert (client_a.calls, client_b.calls) == (1, 0)


def test_a_warm_up_in_one_worker_is_seen_as_warming_up_by_the_other() -> None:
    server = fakeredis.FakeServer()
    worker_a = _worker(_FakeStatusClient(_ASLEEP), _redis_store(server), threads=_Threads(run_now=False))
    client_b = _FakeStatusClient(True)

    worker_a.start_warm_up()

    assert _worker(client_b, _redis_store(server)).status() == "warming_up"
    assert client_b.calls == 0


def test_each_change_is_announced_once() -> None:
    changes: list[AiStatusSnapshot] = []
    gateway = _worker(_FakeStatusClient(_ASLEEP, True), NullCacheStore(), changes)

    gateway.start_warm_up()
    gateway.status()
    gateway.status()

    assert changes == [AiStatusSnapshot("warming_up"), AiStatusSnapshot("ready")]


def test_a_timed_out_warm_up_is_announced_with_its_reason() -> None:
    changes: list[AiStatusSnapshot] = []
    fake_time = _FakeTime()
    status_client = _FakeStatusClient(_ASLEEP, fake_time=fake_time, seconds_per_probe=100)

    _worker(status_client, NullCacheStore(), changes, fake_time).start_warm_up()

    assert changes[-1] == AiStatusSnapshot("unavailable", "timed_out")


def test_without_redis_or_with_a_broken_value_each_worker_uses_its_own_state() -> None:
    server = fakeredis.FakeServer()
    fakeredis.FakeRedis(server=server).set(KEY, '{"availability": "sleeping"}')
    broken = _FakeStatusClient(True)
    offline = _FakeStatusClient(True)

    assert _worker(broken, _redis_store(server)).status() == "ready"
    assert _worker(offline, NullCacheStore()).status() == "ready"
    assert (broken.calls, offline.calls) == (1, 1)


def test_an_event_without_owner_goes_to_every_socket() -> None:
    registry = ConnectionRegistry(5)
    sockets = [object(), object(), object()]
    for index, socket in enumerate(sockets):
        registry.register(socket, uuid.uuid4(), is_admin=index == 0)

    event = RealtimeEvent.now(AI_STATUS_CHANGED, None)

    assert set(registry.recipients_for(event.owner_id)) == set(sockets)
