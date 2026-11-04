"""Cache-aside por usuario: lo invalidado no vuelve a servirse, ni siquiera lo que guardó una lectura en curso."""

import uuid

import fakeredis
from pydantic import BaseModel, TypeAdapter

from app.cache.cache_store import FailureCooldown, RedisCacheStore
from app.cache.owner_cache import CacheEntry, OwnerCache

TTL_SECONDS = 60
OWNER_ID = uuid.uuid4()
OTHER_OWNER_ID = uuid.uuid4()


class _Reading(BaseModel):
    value: int


ENTRY = CacheEntry("reading", TypeAdapter(_Reading))


class _Loader:
    def __init__(self, value: int | None) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> _Reading | None:
        self.calls += 1
        return None if self.value is None else _Reading(value=self.value)


def _cache(server: fakeredis.FakeServer | None = None) -> OwnerCache:
    client = fakeredis.FakeRedis(server=server or fakeredis.FakeServer(), decode_responses=True)
    return OwnerCache(RedisCacheStore(client, FailureCooldown(0)), "test")


def test_a_hit_does_not_load_again() -> None:
    cache = _cache()
    loader = _Loader(1)

    first = cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, loader)
    second = cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, loader)

    assert first == second == _Reading(value=1)
    assert loader.calls == 1


def test_no_data_is_not_cached() -> None:
    cache = _cache()
    loader = _Loader(None)

    cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, loader)
    cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, loader)

    assert loader.calls == 2


def test_invalidate_makes_the_next_read_load_the_new_value() -> None:
    cache = _cache()
    loader = _Loader(1)
    cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, loader)

    loader.value = 2
    cache.invalidate(OWNER_ID)

    assert cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, loader) == _Reading(value=2)


def test_a_read_in_flight_during_a_write_does_not_leave_the_old_value_cached() -> None:
    cache = _cache()

    def load_while_another_request_writes() -> _Reading:
        cache.invalidate(OWNER_ID)
        return _Reading(value=1)

    cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, load_while_another_request_writes)

    assert cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, _Loader(2)) == _Reading(value=2)


def test_invalidating_one_owner_keeps_the_others_cached() -> None:
    cache = _cache()
    cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, _Loader(1))
    cache.get_or_load(OTHER_OWNER_ID, ENTRY, TTL_SECONDS, _Loader(5))

    cache.invalidate(OWNER_ID)
    other = _Loader(6)

    assert cache.get_or_load(OTHER_OWNER_ID, ENTRY, TTL_SECONDS, other) == _Reading(value=5)
    assert other.calls == 0


def test_a_value_saved_with_another_schema_is_read_again() -> None:
    server = fakeredis.FakeServer()
    cache = _cache(server)
    fakeredis.FakeRedis(server=server).set(f"test:owner:{OWNER_ID}:reading", '0:{"unexpected": true}')

    assert cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, _Loader(3)) == _Reading(value=3)


def test_without_redis_every_read_loads_from_the_database() -> None:
    server = fakeredis.FakeServer()
    server.connected = False
    cache = _cache(server)
    loader = _Loader(1)

    cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, loader)
    cache.invalidate(OWNER_ID)
    cache.get_or_load(OWNER_ID, ENTRY, TTL_SECONDS, loader)

    assert loader.calls == 2
