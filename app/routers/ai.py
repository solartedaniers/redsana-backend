from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.ai_gateway.ai_gateway import AiGateway
from app.core.ai_composition import get_ai_gateway
from app.core.security import get_current_claims
from app.schemas.ai import AiStatusRead

# Con sesión pero sin base de datos: el frontend los consulta seguido mientras la IA despierta.
router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(get_current_claims)])


@router.get("/status", response_model=AiStatusRead)
def get_ai_status(gateway: AiGateway = Depends(get_ai_gateway)) -> AiStatusRead:
    return AiStatusRead(status=gateway.status())


@router.post("/warm-up", response_model=AiStatusRead, status_code=status.HTTP_202_ACCEPTED)
def warm_up_ai(
    background_tasks: BackgroundTasks,
    gateway: AiGateway = Depends(get_ai_gateway),
) -> AiStatusRead:
    """Despierta la IA tras iniciar sesión; el arranque en frío tarda, así que corre después de responder."""
    background_tasks.add_task(gateway.warm_up)
    return AiStatusRead(status=gateway.status())
