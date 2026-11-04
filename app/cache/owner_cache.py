import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import TypeAdapter, ValidationError

from app.cache.cache_store import CacheStore

T = TypeVar("T")

_GENERATION_SEPARATOR = ":"
_MISSING_GENERATION = "0"


@dataclass(frozen=True)
class CacheEntry(Generic[T]):
    name: str
    adapter: TypeAdapter[T]


class OwnerCache:
    """Cache-aside por usuario. Cada valor guarda la generación del dueño vigente cuando se leyó de Postgres;
    invalidar sube la generación, así que cualquier valor anterior deja de servir, también el de una lectura que
    estaba en curso mientras se escribía (si no, esa lectura dejaría en la caché el dato viejo)."""

    def __init__(self, store: CacheStore, key_prefix: str) -> None:
        self._store = store
        self._key_prefix = key_prefix

    def get_or_load(self, owner_id: uuid.UUID, entry: CacheEntry[T], ttl_seconds: int, load: Callable[[], T]) -> T:
        """None no se guarda: es "aún no hay datos" y la siguiente consulta debe volver a Postgres."""
        generation, cached = self._store.get_many([self._generation_key(owner_id), self._entry_key(owner_id, entry)])
        generation = generation or _MISSING_GENERATION
        hit = self._decode(cached, generation, entry)
        if hit is not None:
            return hit
        value = load()
        if value is not None:
            payload = entry.adapter.dump_json(value).decode()
            self._store.set(
                self._entry_key(owner_id, entry), f"{generation}{_GENERATION_SEPARATOR}{payload}", ttl_seconds
            )
        return value

    def invalidate(self, owner_id: uuid.UUID) -> None:
        """Se llama después del commit: invalidar antes dejaría que una lectura guarde el dato previo a la escritura."""
        self._store.increment(self._generation_key(owner_id))

    @staticmethod
    def _decode(cached: str | None, generation: str, entry: CacheEntry[T]) -> T | None:
        if cached is None:
            return None
        cached_generation, _, payload = cached.partition(_GENERATION_SEPARATOR)
        if cached_generation != generation:
            return None
        try:
            return entry.adapter.validate_json(payload)
        except ValidationError:
            # Guardado por una versión anterior del esquema: se descarta y se vuelve a leer.
            return None

    def _generation_key(self, owner_id: uuid.UUID) -> str:
        return f"{self._key_prefix}:owner:{owner_id}:generation"

    def _entry_key(self, owner_id: uuid.UUID, entry: CacheEntry[T]) -> str:
        return f"{self._key_prefix}:owner:{owner_id}:{entry.name}"
