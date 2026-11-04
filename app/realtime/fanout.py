import asyncio
import logging

from starlette.websockets import WebSocketDisconnect

from app.realtime.connections import CloseCode, ConnectionRegistry, RealtimeConnection
from app.realtime.events import RealtimeEvent

# Lo que lanza un envío a un socket lento, cerrado o roto.
SEND_FAILURES = (TimeoutError, OSError, RuntimeError, WebSocketDisconnect)

logger = logging.getLogger(__name__)


class BatchedFanOut:
    """Entrega un evento a sus destinatarios por lotes: dentro de cada lote los envíos van en paralelo y entre lotes
    se cede el event loop, así un evento con muchos destinatarios no deja sin atender al resto de la app."""

    def __init__(self, registry: ConnectionRegistry, batch_size: int, send_timeout_seconds: float) -> None:
        self._registry = registry
        self._batch_size = batch_size
        self._send_timeout_seconds = send_timeout_seconds

    async def deliver(self, event: RealtimeEvent) -> int:
        """Devuelve a cuántos sockets de este worker se le envió."""
        payload = event.model_dump_json()
        recipients = self._registry.recipients_for(event.owner_id)
        for start in range(0, len(recipients), self._batch_size):
            batch = recipients[start : start + self._batch_size]
            await asyncio.gather(*(self._send(connection, payload) for connection in batch))
            await asyncio.sleep(0)
        return len(recipients)

    async def _send(self, connection: RealtimeConnection, payload: str) -> None:
        try:
            await asyncio.wait_for(connection.send_text(payload), self._send_timeout_seconds)
        except SEND_FAILURES as error:
            # Lento o roto: se descarta. Al reconectar, el cliente vuelve a pedir el estado por REST.
            logger.info("dropping a realtime client: %r", error)
            self._registry.unregister(connection)
            await close_quietly(connection, CloseCode.TRY_AGAIN_LATER, self._send_timeout_seconds)


async def close_quietly(connection: RealtimeConnection, code: CloseCode, timeout_seconds: float) -> None:
    try:
        await asyncio.wait_for(connection.close(code), timeout_seconds)
    except SEND_FAILURES as error:
        logger.info("could not close a realtime client cleanly: %r", error)
