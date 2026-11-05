import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.realtime.authenticator import RealtimeAuthenticator, RealtimeAuthError, RealtimeIdentity
from app.realtime.connections import CloseCode, WebSocketConnection
from app.realtime.hub import RealtimeHub

AUTH_MESSAGE = "auth"
LOGOUT_MESSAGE = "logout"
READY_MESSAGE = "ready"
PING_MESSAGE = json.dumps({"type": "ping"})


@dataclass(frozen=True)
class RealtimeSessionPolicy:
    allowed_origins: frozenset[str]
    auth_timeout_seconds: float
    ping_interval_seconds: float


class RealtimeSession:
    """Protocolo de un socket: Origin, primer mensaje de autenticación, registro, ping mientras esté abierto y cierre
    al vencer el token. El cliente solo puede mandar auth (renovar el token) y logout; lo demás se ignora."""

    def __init__(
        self,
        websocket: WebSocket,
        hub: RealtimeHub,
        authenticator: RealtimeAuthenticator,
        policy: RealtimeSessionPolicy,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._websocket = websocket
        self._hub = hub
        self._authenticator = authenticator
        self._policy = policy
        self._clock = clock
        self._connection = WebSocketConnection(websocket)

    async def run(self) -> None:
        # Un sitio ajeno no puede abrir el socket con la sesión del navegador (CSWSH): se rechaza antes de aceptar.
        if self._websocket.headers.get("origin") not in self._policy.allowed_origins:
            await self._websocket.close(code=CloseCode.POLICY_VIOLATION)
            return
        await self._websocket.accept()
        async with self._hub.listening() as available:
            if not available:
                await self._connection.close(CloseCode.TRY_AGAIN_LATER)
                return
            await self._run_authenticated()

    async def _run_authenticated(self) -> None:
        identity = await self._authenticate_first_message()
        if identity is None:
            return
        if not self._hub.registry.register(self._connection, identity.user_id, identity.is_admin):
            await self._connection.close(CloseCode.TOO_MANY_CONNECTIONS)
            return
        try:
            await self._connection.send_text(json.dumps({"type": READY_MESSAGE, "server_id": self._hub.server_id}))
            await self._serve(identity)
        except (WebSocketDisconnect, RuntimeError, OSError):
            return
        finally:
            self._hub.registry.unregister(self._connection)

    async def _authenticate_first_message(self) -> RealtimeIdentity | None:
        try:
            message = await asyncio.wait_for(self._websocket.receive(), self._policy.auth_timeout_seconds)
        except TimeoutError:
            await self._connection.close(CloseCode.AUTH_TIMEOUT)
            return None
        if message["type"] == "websocket.disconnect":
            return None
        token = _auth_token(_parse(message))
        if token is None:
            await self._connection.close(CloseCode.UNAUTHORIZED)
            return None
        return await self._validate(token)

    async def _validate(self, token: str) -> RealtimeIdentity | None:
        try:
            identity = await run_in_threadpool(self._authenticator.authenticate, token)
        except RealtimeAuthError as error:
            await self._connection.close(error.close_code)
            return None
        if identity.expires_at <= self._clock():
            await self._connection.close(CloseCode.UNAUTHORIZED)
            return None
        return identity

    async def _serve(self, identity: RealtimeIdentity) -> None:
        while True:
            remaining = identity.expires_at - self._clock()
            if remaining <= 0:
                await self._connection.close(CloseCode.UNAUTHORIZED)
                return
            try:
                message = await asyncio.wait_for(
                    self._websocket.receive(), min(self._policy.ping_interval_seconds, remaining)
                )
            except TimeoutError:
                if identity.expires_at > self._clock():
                    await self._connection.send_text(PING_MESSAGE)
                continue
            if message["type"] == "websocket.disconnect":
                return
            parsed = _parse(message)
            if parsed.get("type") == LOGOUT_MESSAGE:
                await self._connection.close(CloseCode.NORMAL)
                return
            token = _auth_token(parsed)
            if token is None:
                continue
            renewed = await self._validate(token)
            if renewed is None:
                return
            if renewed.user_id != identity.user_id:
                await self._connection.close(CloseCode.UNAUTHORIZED)
                return
            identity = renewed
            self._hub.registry.set_admin(self._connection, identity.is_admin)


def _parse(message: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(message.get("text") or "")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _auth_token(parsed: dict[str, Any]) -> str | None:
    token = parsed.get("token")
    return token if parsed.get("type") == AUTH_MESSAGE and isinstance(token, str) and token else None
