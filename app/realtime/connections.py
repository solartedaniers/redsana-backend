import asyncio
import contextlib
import json
import uuid
from enum import IntEnum
from typing import Protocol

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

CLOSE_MESSAGE = "close"


class CloseCode(IntEnum):
    NORMAL = 1000
    POLICY_VIOLATION = 1008
    TRY_AGAIN_LATER = 1013
    UNAUTHORIZED = 4401
    FORBIDDEN = 4403
    AUTH_TIMEOUT = 4408
    TOO_MANY_CONNECTIONS = 4429


class RealtimeConnection(Protocol):
    async def send_text(self, text: str) -> None: ...

    async def close(self, code: CloseCode) -> None: ...


class WebSocketConnection:
    """Serializa los envíos: el fan-out y el ping pueden escribir a la vez en el mismo socket."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._send_lock = asyncio.Lock()

    async def send_text(self, text: str) -> None:
        async with self._send_lock:
            await self._websocket.send_text(text)

    async def close(self, code: CloseCode) -> None:
        # El proxy de Render no deja pasar el frame de cierre (el cliente ve 1006): el código va antes como mensaje.
        # Puede estar cerrado ya (el cliente se fue o otro camino lo cerró): no hay nada más que hacer.
        with contextlib.suppress(RuntimeError, OSError, WebSocketDisconnect):
            await self.send_text(json.dumps({"type": CLOSE_MESSAGE, "code": int(code)}))
        with contextlib.suppress(RuntimeError, OSError):
            await self._websocket.close(code=code)


class ConnectionRegistry:
    """Sockets autenticados de este worker: los de cada dueño y los de los admins, que reciben de todos."""

    def __init__(self, max_connections_per_user: int) -> None:
        self._max_connections_per_user = max_connections_per_user
        self._by_owner: dict[uuid.UUID, set[RealtimeConnection]] = {}
        self._owner_of: dict[RealtimeConnection, uuid.UUID] = {}
        self._admins: set[RealtimeConnection] = set()

    def register(self, connection: RealtimeConnection, owner_id: uuid.UUID, is_admin: bool) -> bool:
        owned = self._by_owner.setdefault(owner_id, set())
        if len(owned) >= self._max_connections_per_user:
            return False
        owned.add(connection)
        self._owner_of[connection] = owner_id
        self.set_admin(connection, is_admin)
        return True

    def set_admin(self, connection: RealtimeConnection, is_admin: bool) -> None:
        if is_admin:
            self._admins.add(connection)
        else:
            self._admins.discard(connection)

    def unregister(self, connection: RealtimeConnection) -> None:
        owner_id = self._owner_of.pop(connection, None)
        if owner_id is not None:
            owned = self._by_owner.get(owner_id, set())
            owned.discard(connection)
            if not owned:
                self._by_owner.pop(owner_id, None)
        self._admins.discard(connection)

    def connections_of(self, owner_id: uuid.UUID) -> list[RealtimeConnection]:
        return list(self._by_owner.get(owner_id, set()))

    def recipients_for(self, owner_id: uuid.UUID) -> list[RealtimeConnection]:
        return list(self._by_owner.get(owner_id, set()) | self._admins)

    def all(self) -> list[RealtimeConnection]:
        return list(self._owner_of)
