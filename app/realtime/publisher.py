import asyncio
import logging
from concurrent.futures import Future

from app.realtime.event_bus import EventBus
from app.realtime.events import RealtimeEvent

logger = logging.getLogger(__name__)


class EventPublisher:
    """Puente entre los endpoints síncronos (corren en hilos) y el bus asíncrono. Publicar nunca bloquea ni lanza:
    sin event loop (pruebas sin lifespan) no hace nada, y un fallo del bus solo queda en el log."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def detach(self) -> None:
        self._loop = None

    def publish(self, event: RealtimeEvent) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._bus.publish(event), loop)
        except RuntimeError as error:
            logger.warning("realtime event not published: %s", error)
            return
        future.add_done_callback(_log_failure)


def _log_failure(future: Future[None]) -> None:
    if not future.cancelled() and future.exception() is not None:
        logger.warning("realtime event not published: %s", future.exception())
