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

    async def acquire(self) -> bool:
        """Un socket de este worker necesita recibir eventos; responde si el bus está disponible."""
        return self.is_available

    def release(self) -> None:
        """Ese socket se cerró (cada acquire va con un release)."""


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
    publicó él mismo. Solo está suscrito mientras tenga sockets: sin nadie conectado no gasta comandos de Redis (ni el
    SUBSCRIBE ni el PING periódico). Si pierde la suscripción avisa (los sockets se cierran) y se vuelve a suscribir."""

    def __init__(
        self,
        publish_client: redis_async.Redis,
        subscribe_client: redis_async.Redis,
        channel: str,
        retry_seconds: float,
        health_check_seconds: float,
        max_retry_seconds: float | None = None,
        subscribe_timeout_seconds: float = 3.0,
        idle_seconds: float = 60.0,
    ) -> None:
        self._publish_client = publish_client
        self._subscribe_client = subscribe_client
        self._channel = channel
        self._retry_seconds = retry_seconds
        # Con Redis caído (o sin cupo de comandos) la espera se duplica hasta este tope: sin bucle cada pocos segundos.
        self._max_retry_seconds = max(max_retry_seconds or retry_seconds, retry_seconds)
        self._health_check_seconds = health_check_seconds
        # Cuánto espera un socket nuevo a que la suscripción quede lista antes de cerrarse con 1013.
        self._subscribe_timeout_seconds = subscribe_timeout_seconds
        # Sin sockets, la suscripción sigue este tiempo por si alguien reconecta enseguida (recargar la página).
        self._idle_seconds = idle_seconds
        self._on_event: EventHandler | None = None
        self._on_unavailable: UnavailableHandler | None = None
        self._subscribed = asyncio.Event()
        self._listener: asyncio.Task[None] | None = None
        self._users = 0
        self._idle_stop: asyncio.TimerHandle | None = None

    @property
    def is_available(self) -> bool:
        return self._subscribed.is_set()

    async def start(self, on_event: EventHandler, on_unavailable: UnavailableHandler) -> None:
        # No se suscribe todavía: lo hace el primer socket (acquire).
        self._on_event, self._on_unavailable = on_event, on_unavailable

    async def stop(self) -> None:
        self._cancel_idle_stop()
        await self._stop_listening()
        await self._publish_client.aclose()
        await self._subscribe_client.aclose()

    async def publish(self, event: RealtimeEvent) -> None:
        await self._publish_client.publish(self._channel, event.model_dump_json())

    async def acquire(self) -> bool:
        self._users += 1
        self._cancel_idle_stop()
        if self._on_event is None:
            return False
        if self._listener is None or self._listener.done():
            self._listener = asyncio.create_task(self._listen())
        try:
            await asyncio.wait_for(self._subscribed.wait(), self._subscribe_timeout_seconds)
        except TimeoutError:
            return False
        return True

    def release(self) -> None:
        self._users = max(self._users - 1, 0)
        if self._users == 0 and self._listener is not None and self._idle_stop is None:
            self._idle_stop = asyncio.get_running_loop().call_later(
                self._idle_seconds, lambda: asyncio.ensure_future(self._stop_listening())
            )

    def _cancel_idle_stop(self) -> None:
        if self._idle_stop is not None:
            self._idle_stop.cancel()
            self._idle_stop = None

    async def _stop_listening(self) -> None:
        self._idle_stop = None
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
        self._subscribed.clear()

    async def _listen(self) -> None:
        retry_seconds = self._retry_seconds
        while True:
            try:
                async with self._subscribe_client.pubsub() as pubsub:
                    await pubsub.subscribe(self._channel)
                    self._subscribed.set()
                    retry_seconds = self._retry_seconds
                    while True:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=self._health_check_seconds
                        )
                        if message is not None and self._on_event is not None:
                            await self._dispatch(message["data"], self._on_event)
            except (RedisError, OSError) as error:
                logger.warning("realtime subscription lost, retrying in %ss: %s", retry_seconds, error)
            if self._subscribed.is_set():
                self._subscribed.clear()
                if self._on_unavailable is not None:
                    await self._on_unavailable()
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
