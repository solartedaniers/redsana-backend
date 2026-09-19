import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.groq_client import GroqClient, GroqClientError, get_groq_client
from app.core.security import get_current_claims
from app.repositories.alert_sqlalchemy_repository import SqlAlchemyAlertRepository
from app.repositories.device_sqlalchemy_repository import SqlAlchemyDeviceRepository
from app.repositories.network_metrics_sqlalchemy_repository import SqlAlchemyNetworkMetricsRepository
from app.schemas.security_chat import SecurityChatRequest, SecurityChatResponse
from app.services.security_chat_context_service import SecurityChatContextBuilder
from app.services.security_chat_service import SecurityChatService

router = APIRouter(prefix="/api/security-assistant", tags=["security-assistant"])


@router.post("/chat", response_model=SecurityChatResponse)
def send_chat_message(
    payload: SecurityChatRequest,
    claims: dict[str, Any] = Depends(get_current_claims),
    groq_client: GroqClient = Depends(get_groq_client),
    db: Session = Depends(get_db),
) -> SecurityChatResponse:
    context_builder = SecurityChatContextBuilder(
        device_repository=SqlAlchemyDeviceRepository(db),
        alert_repository=SqlAlchemyAlertRepository(db),
        network_metrics_repository=SqlAlchemyNetworkMetricsRepository(db),
    )
    service = SecurityChatService(groq_client, context_builder)
    owner_id = uuid.UUID(claims["sub"])
    try:
        reply = service.ask(owner_id, payload.message)
    except GroqClientError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return SecurityChatResponse(reply=reply)
