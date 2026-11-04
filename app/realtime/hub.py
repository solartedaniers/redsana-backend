import asyncio
import logging
import uuid

from app.realtime.connections import CloseCode, ConnectionRegistry
from app.realtime.event_bus import EventBus
from app.realtime.events import ACCESS_CHANGED, RealtimeEvent
from app.realtime.fanout import BatchedFanOut, close_quietly
from app.realtime.publisher import EventPublisher

logger = logging.getLogger(__name__)


class RealtimeHub:
    """Une el bus, los sockets de este worker y el fan-out. Arranca y se detiene con la app (lifespan)."""

    def __init__(
        self,
        bus: EventBus,
        registry: ConnectionRegistry,
        fanout: BatchedFanOut,
        close_timeout_seconds: float,
        server_id: str | None = None,
    ) -> None:
        # Identifica a este worker en el saludo y en los logs: con varios se ve cuál publica y cuál entrega.
        self.server_id = server_id or uuid.uuid4().hex[:8]
        self._bus = bus
        self.registry = registry
        self._fanout = fanout
        self._close_timeout_seconds = close_timeout_seconds
        self.publisher = EventPublisher(bus, self.server_id)

    @property
    def is_available(self) -> bool:
        return self._bus.is_available

    async def start(self) -> None:
        await self._bus.start(on_event=self._route, on_unavailable=self._close_all)
        self.publisher.attach(asyncio.get_running_loop())

    async def stop(self) -> None:
        self.publisher.detach()
        await self._bus.stop()
        await self._close_all()

    async def _route(self, event: RealtimeEvent) -> None:
        if event.type != ACCESS_CHANGED:
            delivered = await self._fanout.deliver(event)
            logger.info(
                "%s published by %s, delivered by %s to %d sockets", event.type, event.origin, self.server_id, delivered
            )
            return
        # El rol o la cuenta cambió: con 4401 el cliente se vuelve a autenticar y valen el rol y el estado nuevos.
        connections = self.registry.connections_of(event.owner_id)
        for connection in connections:
            self.registry.unregister(connection)
        await asyncio.gather(
            *(close_quietly(c, CloseCode.UNAUTHORIZED, self._close_timeout_seconds) for c in connections)
        )

    async def _close_all(self) -> None:
        """Sin bus no llegarían eventos: cierro con 1013 para que cada cliente vuelva al polling y reintente."""
        connections = self.registry.all()
        if connections:
            logger.warning("closing %d realtime sockets: the event bus is unavailable", len(connections))
        for connection in connections:
            self.registry.unregister(connection)
        await asyncio.gather(
            *(close_quietly(c, CloseCode.TRY_AGAIN_LATER, self._close_timeout_seconds) for c in connections)
        )
