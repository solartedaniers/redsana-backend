import json
import math
from collections.abc import Callable
from dataclasses import dataclass

from app.ai_gateway.ai_gateway import AiAvailability, AiUnavailableReason
from app.cache.cache_store import CacheStore

AVAILABILITIES = ("ready", "warming_up", "unavailable")
REASONS = (None, "timed_out", "service_error")


@dataclass(frozen=True)
class AiStatusSnapshot:
    availability: AiAvailability
    reason: AiUnavailableReason | None = None


AiStatusListener = Callable[[AiStatusSnapshot], None]


class SharedAiStatus:
    """El último estado conocido de la IA en Redis, para que todos los workers lo lean sin consultar cada uno al
    servicio. Postgres no interviene. Sin Redis (o si falla) la caché responde vacío y cada worker usa el suyo."""

    def __init__(self, store: CacheStore, key: str) -> None:
        self._store = store
        self._key = key

    def load(self) -> AiStatusSnapshot | None:
        raw = self._store.get_many([self._key])[0]
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            snapshot = AiStatusSnapshot(data["availability"], data.get("reason"))
        except (ValueError, KeyError, TypeError):
            return None
        if snapshot.availability not in AVAILABILITIES or snapshot.reason not in REASONS:
            return None
        return snapshot

    def save(self, snapshot: AiStatusSnapshot, ttl_seconds: float) -> None:
        payload = json.dumps({"availability": snapshot.availability, "reason": snapshot.reason})
        self._store.set(self._key, payload, max(1, math.ceil(ttl_seconds)))
