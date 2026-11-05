"""Único lugar donde el backend construye el tiempo real: sin REDIS_URL el bus vive en memoria (un solo worker)."""

import logging
from functools import lru_cache

import redis.asyncio as redis_async

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.realtime.authenticator import RealtimeAuthenticator, SupabaseRealtimeAuthenticator
from app.realtime.connections import ConnectionRegistry
from app.realtime.event_bus import EventBus, InMemoryEventBus, RedisEventBus
from app.realtime.fanout import BatchedFanOut
from app.realtime.hub import RealtimeHub
from app.realtime.publisher import EventPublisher
from app.realtime.session import RealtimeSessionPolicy

logger = logging.getLogger(__name__)


def _build_event_bus(settings: Settings) -> EventBus:
    if not settings.redis_url:
        return InMemoryEventBus()
    publish_pool = redis_async.BlockingConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.realtime_redis_max_connections,
        timeout=settings.redis_timeout_seconds,
        socket_timeout=settings.redis_timeout_seconds,
        socket_connect_timeout=settings.redis_timeout_seconds,
        decode_responses=True,
    )
    # La suscripción espera mensajes sin límite de lectura; el PING periódico detecta si la conexión murió.
    subscribe_client = redis_async.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.redis_timeout_seconds,
        socket_keepalive=True,
        health_check_interval=settings.realtime_bus_health_check_seconds,
        decode_responses=True,
    )
    logger.info(
        "redis connections per worker: up to %d (cache %d, publish %d, subscribe 1)",
        settings.redis_connections_per_worker,
        settings.redis_max_connections,
        settings.realtime_redis_max_connections,
    )
    return RedisEventBus(
        publish_client=redis_async.Redis(connection_pool=publish_pool),
        subscribe_client=subscribe_client,
        channel=settings.realtime_channel,
        retry_seconds=settings.realtime_bus_retry_seconds,
        max_retry_seconds=settings.realtime_bus_max_retry_seconds,
        health_check_seconds=settings.realtime_bus_health_check_seconds,
    )


@lru_cache
def get_realtime_hub() -> RealtimeHub:
    # Uno por proceso: los sockets y la suscripción son de este worker.
    settings = get_settings()
    registry = ConnectionRegistry(settings.realtime_max_connections_per_user)
    fanout = BatchedFanOut(registry, settings.realtime_fanout_batch_size, settings.realtime_send_timeout_seconds)
    return RealtimeHub(_build_event_bus(settings), registry, fanout, settings.realtime_send_timeout_seconds)


def get_event_publisher() -> EventPublisher:
    return get_realtime_hub().publisher


def get_realtime_authenticator() -> RealtimeAuthenticator:
    return SupabaseRealtimeAuthenticator(SessionLocal)


def get_realtime_session_policy() -> RealtimeSessionPolicy:
    settings = get_settings()
    return RealtimeSessionPolicy(
        allowed_origins=frozenset(settings.cors_origins_list),
        auth_timeout_seconds=settings.realtime_auth_timeout_seconds,
        ping_interval_seconds=settings.realtime_ping_interval_seconds,
    )
