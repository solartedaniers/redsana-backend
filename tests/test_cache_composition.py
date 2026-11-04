"""La caché se arma desde la configuración: apagada sin REDIS_URL y, con un Redis inalcanzable, nunca rompe nada."""

import time
import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from app.cache.owner_cache import CacheEntry
from app.core import cache_composition
from app.core.config import Settings, get_settings

# Puerto cerrado en la propia máquina: la conexión se rechaza sin salir a la red.
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"
ENTRY = CacheEntry("value", TypeAdapter(int))


@pytest.fixture()
def redis_url(monkeypatch: pytest.MonkeyPatch):
    def configure(url: str) -> None:
        monkeypatch.setenv("REDIS_URL", url)
        get_settings.cache_clear()
        cache_composition.get_owner_cache.cache_clear()

    yield configure
    get_settings.cache_clear()
    cache_composition.get_owner_cache.cache_clear()


def test_an_unreachable_redis_answers_from_the_loader_within_the_timeout(redis_url) -> None:
    redis_url(UNREACHABLE_REDIS_URL)
    cache = cache_composition.get_owner_cache()

    started = time.perf_counter()
    value = cache.get_or_load(uuid.uuid4(), ENTRY, 60, lambda: 7)
    cache.invalidate(uuid.uuid4())

    assert value == 7
    assert time.perf_counter() - started < 5 * get_settings().redis_timeout_seconds + 1


def test_redis_url_must_use_a_redis_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "http://example.invalid:6379")

    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings()
