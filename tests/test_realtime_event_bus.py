"""El bus entrega lo publicado: en memoria dentro del worker y con Pub/Sub entre workers. Si Redis cae, avisa y se
vuelve a suscribir; publicar desde un endpoint nunca lanza ni bloquea."""

import asyncio
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import fakeredis
import pytest
from redis.exceptions import RedisError

from app.realtime.connections import ConnectionRegistry
from app.realtime.event_bus import InMemoryEventBus, RedisEventBus
from app.realtime.events import DEVICES_UPDATED, RealtimeEvent
from app.realtime.fanout import BatchedFanOut
from app.realtime.hub import RealtimeHub
from app.realtime.publisher import EventPublisher

CHANNEL = "test:events"
FAST_SECONDS = 0.05
WAIT_SECONDS = 3.0


def _event() -> RealtimeEvent:
    return RealtimeEvent(type=DEVICES_UPDATED, owner_id=uuid.uuid4(), at=datetime.now(UTC))


def _redis_bus(server: fakeredis.FakeServer) -> RedisEventBus:
    return RedisEventBus(
        publish_client=fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
        subscribe_client=fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
        channel=CHANNEL,
        retry_seconds=FAST_SECONDS,
        health_check_seconds=FAST_SECONDS,
        subscribe_timeout_seconds=FAST_SECONDS,
        idle_seconds=FAST_SECONDS,
    )


async def _until(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(WAIT_SECONDS):
        while not condition():
            await asyncio.sleep(FAST_SECONDS / 5)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[RealtimeEvent] = []
        self.unavailable = 0

    async def on_event(self, event: RealtimeEvent) -> None:
        self.events.append(event)

    async def on_unavailable(self) -> None:
        self.unavailable += 1


def test_the_in_memory_bus_delivers_only_after_starting() -> None:
    async def scenario() -> _Recorder:
        bus, recorder = InMemoryEventBus(), _Recorder()
        await bus.publish(_event())
        assert not bus.is_available
        await bus.start(recorder.on_event, recorder.on_unavailable)
        await bus.publish(_event())
        return recorder

    assert len(asyncio.run(scenario()).events) == 1


def test_pub_sub_delivers_an_event_to_every_worker_including_the_publisher() -> None:
    """El backplane: lo que publica el worker A le llega también al worker B, que tiene otros sockets."""
    event = _event()

    async def scenario() -> tuple[_Recorder, _Recorder]:
        server = fakeredis.FakeServer()
        worker_a, worker_b = _redis_bus(server), _redis_bus(server)
        recorder_a, recorder_b = _Recorder(), _Recorder()
        await worker_a.start(recorder_a.on_event, recorder_a.on_unavailable)
        await worker_b.start(recorder_b.on_event, recorder_b.on_unavailable)
        await worker_a.acquire()
        await worker_b.acquire()
        await _until(lambda: worker_a.is_available and worker_b.is_available)
        await worker_a.publish(event)
        await _until(lambda: recorder_a.events and recorder_b.events)
        await worker_a.stop()
        await worker_b.stop()
        return recorder_a, recorder_b

    recorder_a, recorder_b = asyncio.run(scenario())

    assert recorder_a.events == recorder_b.events == [event]


def test_a_malformed_message_is_ignored_and_the_subscription_keeps_working() -> None:
    event = _event()

    async def scenario() -> _Recorder:
        server = fakeredis.FakeServer()
        bus, recorder = _redis_bus(server), _Recorder()
        await bus.start(recorder.on_event, recorder.on_unavailable)
        await bus.acquire()
        await _until(lambda: bus.is_available)
        await fakeredis.aioredis.FakeRedis(server=server).publish(CHANNEL, '{"v": 2}')
        await bus.publish(event)
        await _until(lambda: recorder.events)
        await bus.stop()
        return recorder

    assert asyncio.run(scenario()).events == [event]


def test_losing_redis_notifies_once_and_the_subscription_comes_back() -> None:
    async def scenario() -> tuple[_Recorder, bool]:
        server = fakeredis.FakeServer()
        bus, recorder = _redis_bus(server), _Recorder()
        await bus.start(recorder.on_event, recorder.on_unavailable)
        await bus.acquire()
        await _until(lambda: bus.is_available)
        server.connected = False
        await _until(lambda: not bus.is_available)
        await asyncio.sleep(FAST_SECONDS * 3)
        server.connected = True
        await _until(lambda: bus.is_available)
        await bus.publish(_event())
        await _until(lambda: recorder.events)
        recovered = bus.is_available
        await bus.stop()
        return recorder, recovered

    recorder, recovered = asyncio.run(scenario())

    assert recorder.unavailable == 1
    assert recovered


def test_without_redis_the_bus_is_unavailable_and_publishing_fails_inside_the_bus() -> None:
    async def scenario() -> bool:
        server = fakeredis.FakeServer()
        server.connected = False
        bus, recorder = _redis_bus(server), _Recorder()
        await bus.start(recorder.on_event, recorder.on_unavailable)
        await bus.acquire()
        await asyncio.sleep(FAST_SECONDS * 3)
        with pytest.raises(RedisError):
            await bus.publish(_event())
        available = bus.is_available
        await bus.stop()
        return available

    assert asyncio.run(scenario()) is False


def test_with_redis_down_each_retry_waits_twice_as_long_up_to_the_cap(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        server = fakeredis.FakeServer()
        server.connected = False
        bus = RedisEventBus(
            publish_client=fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
            subscribe_client=fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
            channel=CHANNEL,
            retry_seconds=0.01,
            health_check_seconds=FAST_SECONDS,
            max_retry_seconds=0.04,
            subscribe_timeout_seconds=FAST_SECONDS,
        )
        recorder = _Recorder()
        await bus.start(recorder.on_event, recorder.on_unavailable)
        await bus.acquire()
        await _until(lambda: len(caplog.records) >= 5)
        await bus.stop()

    with caplog.at_level("WARNING", logger="app.realtime.event_bus"):
        asyncio.run(scenario())

    waits = [record.getMessage().split("retrying in ")[1].split("s:")[0] for record in caplog.records[:5]]
    assert waits == ["0.01", "0.02", "0.04", "0.04", "0.04"]


def test_starting_the_hub_without_redis_schedules_no_background_work() -> None:
    """Sin sockets no puede haber tráfico programado: con el bus en memoria arrancar no crea ninguna tarea."""

    async def scenario() -> int:
        hub = RealtimeHub(
            InMemoryEventBus(), ConnectionRegistry(5), BatchedFanOut(ConnectionRegistry(5), 1, 1), FAST_SECONDS
        )
        before = len(asyncio.all_tasks())
        await hub.start()
        after = len(asyncio.all_tasks())
        await hub.stop()
        return after - before

    assert asyncio.run(scenario()) == 0


class _LoopThread:
    """Un event loop en otro hilo, como el de la app mientras los endpoints síncronos corren en el pool."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coroutine: Awaitable[None]) -> None:
        asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(WAIT_SECONDS)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(WAIT_SECONDS)
        self.loop.close()


@pytest.fixture()
def loop_thread():
    thread = _LoopThread()
    yield thread
    thread.close()


def test_the_publisher_does_nothing_without_an_event_loop() -> None:
    EventPublisher(InMemoryEventBus(), "a").publish(_event())


def test_the_publisher_delivers_from_a_worker_thread(loop_thread: _LoopThread) -> None:
    bus, recorder = InMemoryEventBus(), _Recorder()
    loop_thread.run(bus.start(recorder.on_event, recorder.on_unavailable))
    publisher = EventPublisher(bus, "a")
    publisher.attach(loop_thread.loop)
    event = _event()

    publisher.publish(event)
    loop_thread.run(_until(lambda: recorder.events))

    assert recorder.events == [event.model_copy(update={"origin": "a"})]


def test_a_failing_bus_never_raises_into_the_caller(loop_thread: _LoopThread) -> None:
    server = fakeredis.FakeServer()
    server.connected = False
    publisher = EventPublisher(_redis_bus(server), "a")
    publisher.attach(loop_thread.loop)

    publisher.publish(_event())
    loop_thread.run(asyncio.sleep(FAST_SECONDS))


class _SocketStub:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code) -> None:
        return None


def test_with_two_workers_the_log_says_which_one_published_and_which_one_delivered(
    loop_thread: _LoopThread, caplog: pytest.LogCaptureFixture
) -> None:
    """El worker A publica (desde un hilo, como un endpoint) y el B, que tiene el socket del dueño, lo entrega."""
    server = fakeredis.FakeServer()
    registry_a, registry_b = ConnectionRegistry(5), ConnectionRegistry(5)
    bus_a, bus_b = _redis_bus(server), _redis_bus(server)
    hub_a = RealtimeHub(bus_a, registry_a, BatchedFanOut(registry_a, 10, 1), 1, server_id="worker-a")
    hub_b = RealtimeHub(bus_b, registry_b, BatchedFanOut(registry_b, 10, 1), 1, server_id="worker-b")
    event, socket = _event(), _SocketStub()
    registry_b.register(socket, event.owner_id, is_admin=False)
    for hub in (hub_a, hub_b):
        loop_thread.run(hub.start())
    for bus in (bus_a, bus_b):
        loop_thread.run(bus.acquire())
    loop_thread.run(_until(lambda: hub_a.is_available and hub_b.is_available))

    with caplog.at_level("INFO", logger="app.realtime.hub"):
        hub_a.publisher.publish(event)
        loop_thread.run(_until(lambda: len(_deliveries(caplog)) == 2))
    for hub in (hub_a, hub_b):
        loop_thread.run(hub.stop())

    assert RealtimeEvent.model_validate_json(socket.sent[0]).origin == "worker-a"
    assert sorted(_deliveries(caplog)) == [
        "devices.updated published by worker-a, delivered by worker-a to 0 sockets",
        "devices.updated published by worker-a, delivered by worker-b to 1 sockets",
    ]


def _deliveries(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if " published by " in record.getMessage()]


async def _subscribers(server: fakeredis.FakeServer) -> int:
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    counts = await client.pubsub_numsub(CHANNEL)
    await client.aclose()
    return counts[0][1]


def test_without_sockets_the_bus_does_not_subscribe_and_stops_after_the_last_one_leaves() -> None:
    """Sin nadie conectado no hay SUBSCRIBE ni PING periódicos: ningún comando de Redis gastado."""

    async def scenario() -> list[int]:
        server = fakeredis.FakeServer()
        bus, recorder = _redis_bus(server), _Recorder()
        await bus.start(recorder.on_event, recorder.on_unavailable)
        await asyncio.sleep(FAST_SECONDS * 2)
        baseline_tasks = len(asyncio.all_tasks())
        counts = [await _subscribers(server)]
        assert await bus.acquire() is True
        assert await bus.acquire() is True
        counts.append(await _subscribers(server))
        bus.release()
        await asyncio.sleep(FAST_SECONDS * 2)
        counts.append(await _subscribers(server))
        bus.release()
        await _until(lambda: not bus.is_available)
        await asyncio.sleep(FAST_SECONDS)
        # Sin la tarea que escucha no queda conexión suscrita ni PING (fakeredis no limpia al cerrar; Redis sí).
        counts.append(len(asyncio.all_tasks()) - baseline_tasks)
        await bus.stop()
        return counts

    assert asyncio.run(scenario()) == [0, 1, 1, 0]


def test_reconnecting_before_the_idle_time_keeps_the_same_subscription() -> None:
    async def scenario() -> tuple[bool, bool]:
        server = fakeredis.FakeServer()
        bus, recorder = _redis_bus(server), _Recorder()
        await bus.start(recorder.on_event, recorder.on_unavailable)
        await bus.acquire()
        bus.release()
        reacquired = await bus.acquire()
        await asyncio.sleep(FAST_SECONDS * 3)
        still_available = bus.is_available
        await bus.stop()
        return reacquired, still_available

    assert asyncio.run(scenario()) == (True, True)


def test_with_redis_down_a_socket_gets_false_quickly_and_retries_stop_once_nobody_is_connected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> tuple[bool, float, int, int]:
        server = fakeredis.FakeServer()
        server.connected = False
        bus, recorder = _redis_bus(server), _Recorder()
        await bus.start(recorder.on_event, recorder.on_unavailable)
        started = time.perf_counter()
        acquired = await bus.acquire()
        waited = time.perf_counter() - started
        bus.release()
        await asyncio.sleep(FAST_SECONDS * 3)
        retries_after_idle = len(caplog.records)
        await asyncio.sleep(FAST_SECONDS * 6)
        await bus.stop()
        return acquired, waited, retries_after_idle, len(caplog.records)

    with caplog.at_level("WARNING", logger="app.realtime.event_bus"):
        acquired, waited, retries_after_idle, retries_at_the_end = asyncio.run(scenario())

    assert acquired is False
    assert waited < FAST_SECONDS * 4
    assert retries_at_the_end == retries_after_idle
