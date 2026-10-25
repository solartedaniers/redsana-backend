from fastapi import APIRouter, Depends, status

from app.ai_gateway.ai_gateway import AiGateway
from app.core.ai_composition import get_ai_gateway
from app.core.security import get_current_claims
from app.schemas.ai import AiStatusRead

# Con sesión pero sin base de datos: el frontend los consulta seguido mientras la IA despierta.
router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(get_current_claims)])


def _status_read(gateway: AiGateway) -> AiStatusRead:
    availability = gateway.status()
    reason = gateway.unavailable_reason() if availability == "unavailable" else None
    return AiStatusRead(status=availability, reason=reason)


@router.get("/status", response_model=AiStatusRead)
def get_ai_status(gateway: AiGateway = Depends(get_ai_gateway)) -> AiStatusRead:
    """Lee el estado que mantiene el calentamiento. Si no hay uno en curso, no quedó «no disponible» y el dato guardado
    venció, hace una consulta corta a /health de la IA, y esa consulta la despierta si estaba dormida."""
    return _status_read(gateway)


@router.post("/warm-up", response_model=AiStatusRead, status_code=status.HTTP_202_ACCEPTED)
def warm_up_ai(gateway: AiGateway = Depends(get_ai_gateway)) -> AiStatusRead:
    """Despierta la IA tras iniciar sesión, al reintentar o al abrir el chat. El calentamiento corre en su propio hilo,
    así que sigue aunque el cliente se desconecte; si ya hay uno en curso no lanza otro."""
    gateway.start_warm_up()
    return _status_read(gateway)
