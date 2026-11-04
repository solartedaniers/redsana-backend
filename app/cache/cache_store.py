import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TypeVar

import redis

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheStore(ABC):
    """Almacén clave-valor de la caché. Nunca lanza: si falla responde como si no hubiera nada guardado."""

    @abstractmethod
    def get_many(self, keys: list[str]) -> list[str | None]: ...

    @abstractmethod
    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    @abstractmethod
    def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> None: ...


class NullCacheStore(CacheStore):
    """Sin REDIS_URL: todo es un fallo de caché y cada lectura va a Postgres."""

    def get_many(self, keys: list[str]) -> list[str | None]:
        return [None] * len(keys)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        return None

    def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> None:
        return None


class FailureCooldown:
    """Tras un fallo, durante cooldown_seconds no se vuelve a intentar: con Redis caído cada petición pagaría el
    timeout completo antes de ir a Postgres."""

    def __init__(self, cooldown_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._retry_at = 0.0

    def is_cooling_down(self) -> bool:
        return self._clock() < self._retry_at

    def record_failure(self) -> None:
        self._retry_at = self._clock() + self._cooldown_seconds


class RedisCacheStore(CacheStore):
    def __init__(self, client: redis.Redis, cooldown: FailureCooldown) -> None:
        self._client = client
        self._cooldown = cooldown

    def get_many(self, keys: list[str]) -> list[str | None]:
        return self._run(lambda: self._client.mget(keys), [None] * len(keys))

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._run(lambda: self._client.set(key, value, ex=ttl_seconds), None)

    def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> None:
        self._run(lambda: self._client.set(key, value, ex=ttl_seconds, nx=True), None)

    def _run(self, command: Callable[[], T], fallback: T) -> T:
        if self._cooldown.is_cooling_down():
            return fallback
        try:
            return command()
        except redis.RedisError as error:
            self._cooldown.record_failure()
            logger.warning("redis unavailable, reading from the database: %s", error)
            return fallback
