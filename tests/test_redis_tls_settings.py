"""Upstash exige TLS (rediss://): la caché, la publicación y la suscripción usan conexiones TLS que verifican el
certificado y el nombre del servidor, y no mandan CLIENT SETINFO al conectar (Upstash cobra cada comando). Solo se
construyen los clientes; ninguna prueba se conecta."""

import ssl

import pytest
import redis
import redis.asyncio as redis_async

from app.core import cache_composition, realtime_composition
from app.core.config import get_settings

UPSTASH_LIKE_URL = "rediss://default:not-a-real-password@example.upstash.io:6379"


@pytest.fixture()
def tls_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REDIS_URL", UPSTASH_LIKE_URL)
    get_settings.cache_clear()
    cache_composition.get_cache_store.cache_clear()
    yield get_settings()
    get_settings.cache_clear()
    cache_composition.get_cache_store.cache_clear()


def test_the_cache_uses_tls_and_verifies_the_certificate(tls_settings) -> None:
    pool = cache_composition.get_cache_store()._client.connection_pool

    assert pool.connection_class is redis.connection.SSLConnection
    connection = pool.make_connection()
    assert (connection.cert_reqs, connection.check_hostname) == (ssl.CERT_REQUIRED, True)
    assert connection.driver_info is None
    assert pool.max_connections == tls_settings.redis_max_connections


def test_publishing_and_subscribing_use_tls_and_verify_the_certificate(tls_settings) -> None:
    bus = realtime_composition._build_event_bus(tls_settings)

    for client in (bus._publish_client, bus._subscribe_client):
        pool = client.connection_pool
        assert pool.connection_class is redis_async.connection.SSLConnection
        connection = pool.make_connection()
        context = connection.ssl_context
        assert connection.driver_info is None
        assert (context.cert_reqs, context.check_hostname) == (ssl.CERT_REQUIRED, True)
    assert bus._publish_client.connection_pool.max_connections == tls_settings.realtime_redis_max_connections
