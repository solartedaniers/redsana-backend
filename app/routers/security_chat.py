from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.groq_client import GroqClient, GroqClientError, get_groq_client
from app.core.security import get_current_claims
from app.schemas.security_chat import SecurityChatRequest, SecurityChatResponse
from app.services.security_chat_service import SecurityChatService

router = APIRouter(prefix="/api/security-assistant", tags=["security-assistant"])


@router.post("/chat", response_model=SecurityChatResponse)
def send_chat_message(
    payload: SecurityChatRequest,
    claims: dict[str, Any] = Depends(get_current_claims),
    groq_client: GroqClient = Depends(get_groq_client),
) -> SecurityChatResponse:
    service = SecurityChatService(groq_client)
    try:
        reply = service.ask(payload.message)
    except GroqClientError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return SecurityChatResponse(reply=reply)
