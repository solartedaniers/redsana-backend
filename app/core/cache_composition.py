"""Único lugar donde el backend construye la caché: sin REDIS_URL queda apagada y todo se lee de Postgres."""

from functools import lru_cache

import redis

from app.cache.cache_store import CacheStore, FailureCooldown, NullCacheStore, RedisCacheStore
from app.cache.owner_cache import OwnerCache
from app.core.config import get_settings


def _build_cache_store() -> CacheStore:
    settings = get_settings()
    if not settings.redis_url:
        return NullCacheStore()
    # Bloqueante y con tope: más hilos que conexiones esperan un rato corto en vez de abrir otra y pasar el límite.
    pool = redis.BlockingConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        timeout=settings.redis_timeout_seconds,
        socket_timeout=settings.redis_timeout_seconds,
        socket_connect_timeout=settings.redis_timeout_seconds,
        decode_responses=True,
    )
    return RedisCacheStore(redis.Redis(connection_pool=pool), FailureCooldown(settings.redis_failure_cooldown_seconds))


@lru_cache
def get_owner_cache() -> OwnerCache:
    # Uno por proceso: comparte el pool de conexiones y el enfriamiento tras un fallo entre todas las peticiones.
    return OwnerCache(_build_cache_store(), get_settings().cache_key_prefix)
