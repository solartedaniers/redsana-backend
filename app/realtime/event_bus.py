import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

import redis.asyncio as redis_async
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.realtime.events import RealtimeEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[RealtimeEvent], Awaitable[None]]
UnavailableHandler = Callable[[], Awaitable[None]]


class EventBus(ABC):
    """Reparte cada evento publicado a on_event de todos los workers suscritos."""

    @property
    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    async def start(self, on_event: EventHandler, on_unavailable: UnavailableHandler) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def publish(self, event: RealtimeEvent) -> None: ...


class InMemoryEventBus(EventBus):
    """Sin REDIS_URL: un solo worker, entrega directa en el mismo proceso."""

    def __init__(self) -> None:
        self._on_event: EventHandler | None = None

    @property
    def is_available(self) -> bool:
        return self._on_event is not None

    async def start(self, on_event: EventHandler, on_unavailable: UnavailableHandler) -> None:
        self._on_event = on_event

    async def stop(self) -> None:
        self._on_event = None

    async def publish(self, event: RealtimeEvent) -> None:
        if self._on_event is not None:
            await self._on_event(event)


class RedisEventBus(EventBus):
    """Backplane Pub/Sub: cada worker publica en el canal y entrega a sus sockets lo que recibe de él, también lo que
    publicó él mismo. Si pierde la suscripción avisa (los sockets se cierran) y se vuelve a suscribir sola."""

    def __init__(
        self,
        publish_client: redis_async.Redis,
        subscribe_client: redis_async.Redis,
        channel: str,
        retry_seconds: float,
        health_check_seconds: float,
        max_retry_seconds: float | None = None,
    ) -> None:
        self._publish_client = publish_client
        self._subscribe_client = subscribe_client
        self._channel = channel
        self._retry_seconds = retry_seconds
        # Con Redis caído (o sin cupo de comandos) la espera se duplica hasta este tope: sin bucle cada pocos segundos.
        self._max_retry_seconds = max(max_retry_seconds or retry_seconds, retry_seconds)
        self._health_check_seconds = health_check_seconds
        self._available = False
        self._listener: asyncio.Task[None] | None = None

    @property
    def is_available(self) -> bool:
        return self._available

    async def start(self, on_event: EventHandler, on_unavailable: UnavailableHandler) -> None:
        self._listener = asyncio.create_task(self._listen(on_event, on_unavailable))

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
        self._available = False
        await self._publish_client.aclose()
        await self._subscribe_client.aclose()

    async def publish(self, event: RealtimeEvent) -> None:
        await self._publish_client.publish(self._channel, event.model_dump_json())

    async def _listen(self, on_event: EventHandler, on_unavailable: UnavailableHandler) -> None:
        retry_seconds = self._retry_seconds
        while True:
            try:
                async with self._subscribe_client.pubsub() as pubsub:
                    await pubsub.subscribe(self._channel)
                    self._available = True
                    retry_seconds = self._retry_seconds
                    while True:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=self._health_check_seconds
                        )
                        if message is not None:
                            await self._dispatch(message["data"], on_event)
            except (RedisError, OSError) as error:
                logger.warning("realtime subscription lost, retrying in %ss: %s", retry_seconds, error)
            if self._available:
                self._available = False
                await on_unavailable()
            await asyncio.sleep(retry_seconds)
            retry_seconds = min(retry_seconds * 2, self._max_retry_seconds)

    @staticmethod
    async def _dispatch(raw: str, on_event: EventHandler) -> None:
        try:
            event = RealtimeEvent.model_validate_json(raw)
        except ValidationError:
            logger.warning("ignoring a malformed realtime event")
            return
        try:
            await on_event(event)
        except Exception:
            # Un fallo al repartir un evento no puede cortar la suscripción para los siguientes.
            logger.exception("realtime event delivery failed")
