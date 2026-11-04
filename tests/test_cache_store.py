"""El almacén de la caché nunca rompe una petición: con Redis caído responde vacío y deja de intentarlo un rato."""

import fakeredis

from app.cache.cache_store import FailureCooldown, NullCacheStore, RedisCacheStore

COOLDOWN_SECONDS = 30.0


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _store(server: fakeredis.FakeServer, clock: _Clock | None = None) -> RedisCacheStore:
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    return RedisCacheStore(client, FailureCooldown(COOLDOWN_SECONDS, clock or _Clock()))


def test_set_stores_with_the_ttl_and_get_many_reads_in_order() -> None:
    server = fakeredis.FakeServer()
    store = _store(server)

    store.set("a", "1", ttl_seconds=60)

    assert store.get_many(["missing", "a"]) == [None, "1"]
    assert 0 < fakeredis.FakeRedis(server=server).ttl("a") <= 60


def test_increment_starts_a_missing_key_at_one() -> None:
    store = _store(fakeredis.FakeServer())

    store.increment("generation")
    store.increment("generation")

    assert store.get_many(["generation"]) == ["2"]


def test_a_failing_redis_answers_empty_instead_of_raising() -> None:
    server = fakeredis.FakeServer()
    server.connected = False
    store = _store(server)

    assert store.get_many(["a", "b"]) == [None, None]
    store.set("a", "1", ttl_seconds=60)
    store.increment("generation")


def test_after_a_failure_redis_is_not_retried_until_the_cooldown_ends() -> None:
    server = fakeredis.FakeServer()
    clock = _Clock()
    store = _store(server, clock)
    store.set("a", "1", ttl_seconds=600)
    server.connected = False
    store.get_many(["a"])
    server.connected = True

    assert store.get_many(["a"]) == [None]
    clock.now += COOLDOWN_SECONDS
    assert store.get_many(["a"]) == ["1"]


def test_the_null_store_is_always_a_miss() -> None:
    store = NullCacheStore()
    store.set("a", "1", ttl_seconds=60)
    store.increment("generation")

    assert store.get_many(["a", "generation"]) == [None, None]
