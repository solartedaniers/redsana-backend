from fastapi import APIRouter, Depends, WebSocket

from app.core.realtime_composition import get_realtime_authenticator, get_realtime_hub, get_realtime_session_policy
from app.realtime.authenticator import RealtimeAuthenticator
from app.realtime.hub import RealtimeHub
from app.realtime.session import RealtimeSession, RealtimeSessionPolicy

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


@router.websocket("/ws")
async def realtime_socket(
    websocket: WebSocket,
    hub: RealtimeHub = Depends(get_realtime_hub),
    authenticator: RealtimeAuthenticator = Depends(get_realtime_authenticator),
    policy: RealtimeSessionPolicy = Depends(get_realtime_session_policy),
) -> None:
    """El JWT nunca va en la URL: llega en el primer mensaje {"type": "auth", "token": ...}."""
    await RealtimeSession(websocket, hub, authenticator, policy).run()
