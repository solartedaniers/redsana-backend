"""El arranque falla si los workers pedirían más conexiones de las que admite el Key Value (50 en el plan gratuito)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

REDIS_URL = "redis://localhost:6379"


def test_one_worker_with_the_defaults_uses_13_of_the_50_connections() -> None:
    settings = Settings(redis_url=REDIS_URL)

    assert settings.redis_connections_per_worker == 13


def test_too_many_workers_for_the_key_value_fail_at_startup() -> None:
    with pytest.raises(ValidationError):
        Settings(redis_url=REDIS_URL, web_concurrency=4)


def test_without_redis_the_connection_limit_does_not_apply() -> None:
    assert Settings(redis_url="", web_concurrency=4).web_concurrency == 4


@pytest.mark.parametrize("override", [{"realtime_fanout_batch_size": 0}, {"realtime_send_timeout_seconds": 0}])
def test_invalid_realtime_values_fail_at_startup(override: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**override)
