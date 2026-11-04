"""Fan-out por lotes: cada evento llega solo a su dueño y a los admins, por lotes que no bloquean el event loop, y un
cliente lento o roto se descarta sin frenar a los demás."""

import asyncio
import time
import uuid
from datetime import UTC, datetime

from app.realtime.connections import CloseCode, ConnectionRegistry
from app.realtime.events import MEASUREMENT_CREATED, RealtimeEvent
from app.realtime.fanout import BatchedFanOut

OWNER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
SEND_TIMEOUT_SECONDS = 0.05
MAX_PER_USER = 5


class _Connection:
    def __init__(self) -> None:
        self.received: list[str] = []
        self.closed_with: CloseCode | None = None

    async def send_text(self, text: str) -> None:
        self.received.append(text)

    async def close(self, code: CloseCode) -> None:
        self.closed_with = code


class _SlowConnection(_Connection):
    async def send_text(self, text: str) -> None:
        await asyncio.sleep(10)


class _BrokenConnection(_Connection):
    async def send_text(self, text: str) -> None:
        raise OSError("connection reset")


class _InFlightTracker:
    def __init__(self) -> None:
        self.current = 0
        self.peak = 0


class _TrackedConnection(_Connection):
    def __init__(self, tracker: _InFlightTracker) -> None:
        super().__init__()
        self._tracker = tracker

    async def send_text(self, text: str) -> None:
        self._tracker.current += 1
        self._tracker.peak = max(self._tracker.peak, self._tracker.current)
        await asyncio.sleep(0)
        self._tracker.current -= 1
        self.received.append(text)


def _event(owner_id: uuid.UUID = OWNER_ID) -> RealtimeEvent:
    return RealtimeEvent(type=MEASUREMENT_CREATED, owner_id=owner_id, data={"latency_ms": 20}, at=datetime.now(UTC))


def _registry(max_per_user: int = MAX_PER_USER) -> ConnectionRegistry:
    return ConnectionRegistry(max_per_user)


def test_an_event_reaches_its_owner_and_the_admins_but_never_another_user() -> None:
    registry = _registry()
    owner, other, admin = _Connection(), _Connection(), _Connection()
    registry.register(owner, OWNER_ID, is_admin=False)
    registry.register(other, OTHER_ID, is_admin=False)
    registry.register(admin, uuid.uuid4(), is_admin=True)

    asyncio.run(BatchedFanOut(registry, 10, SEND_TIMEOUT_SECONDS).deliver(_event()))

    assert len(owner.received) == len(admin.received) == 1
    assert other.received == []
    assert RealtimeEvent.model_validate_json(owner.received[0]).owner_id == OWNER_ID


def test_an_admin_who_owns_the_event_receives_it_once() -> None:
    registry = _registry()
    admin = _Connection()
    registry.register(admin, OWNER_ID, is_admin=True)

    asyncio.run(BatchedFanOut(registry, 10, SEND_TIMEOUT_SECONDS).deliver(_event()))

    assert len(admin.received) == 1


def test_a_user_cannot_register_more_than_the_limit_in_a_worker() -> None:
    registry = _registry()
    accepted = [registry.register(_Connection(), OWNER_ID, is_admin=False) for _ in range(MAX_PER_USER + 1)]

    assert accepted == [True] * MAX_PER_USER + [False]
    assert registry.register(_Connection(), OTHER_ID, is_admin=False)


def test_sends_never_exceed_the_batch_size_at_once() -> None:
    registry = _registry(max_per_user=1000)
    tracker = _InFlightTracker()
    connections = [_TrackedConnection(tracker) for _ in range(120)]
    for connection in connections:
        registry.register(connection, OWNER_ID, is_admin=False)

    asyncio.run(BatchedFanOut(registry, 50, SEND_TIMEOUT_SECONDS).deliver(_event()))

    assert tracker.peak == 50
    assert all(len(connection.received) == 1 for connection in connections)


def test_a_slow_client_is_dropped_without_delaying_the_others() -> None:
    registry = _registry()
    slow, fast = _SlowConnection(), _Connection()
    registry.register(slow, OWNER_ID, is_admin=False)
    registry.register(fast, OWNER_ID, is_admin=False)

    started = time.perf_counter()
    asyncio.run(BatchedFanOut(registry, 10, SEND_TIMEOUT_SECONDS).deliver(_event()))

    assert time.perf_counter() - started < 1
    assert len(fast.received) == 1
    assert slow.closed_with == CloseCode.TRY_AGAIN_LATER
    assert registry.recipients_for(OWNER_ID) == [fast]


def test_a_broken_client_is_dropped_and_the_rest_still_receive() -> None:
    registry = _registry()
    broken, healthy = _BrokenConnection(), _Connection()
    registry.register(broken, OWNER_ID, is_admin=False)
    registry.register(healthy, OWNER_ID, is_admin=False)

    asyncio.run(BatchedFanOut(registry, 1, SEND_TIMEOUT_SECONDS).deliver(_event()))

    assert len(healthy.received) == 1
    assert broken.closed_with == CloseCode.TRY_AGAIN_LATER
    assert registry.recipients_for(OWNER_ID) == [healthy]


def test_the_event_loop_keeps_serving_during_a_large_fan_out() -> None:
    recipients = 5000
    batch_size = 50
    registry = _registry(max_per_user=recipients)
    for _ in range(recipients):
        registry.register(_Connection(), OWNER_ID, is_admin=False)

    async def scenario() -> int:
        fanout = asyncio.create_task(BatchedFanOut(registry, batch_size, SEND_TIMEOUT_SECONDS).deliver(_event()))
        ticks = 0
        while not fanout.done():
            ticks += 1
            await asyncio.sleep(0)
        await fanout
        return ticks

    ticks = asyncio.run(scenario())

    assert ticks >= recipients // batch_size
