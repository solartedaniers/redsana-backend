from pydantic import BaseModel

from app.ai_gateway.ai_gateway import AiAvailability, AiUnavailableReason


class AiStatusRead(BaseModel):
    status: AiAvailability
    # Campo nuevo y opcional: los clientes que no lo conocen (escritorio 0.1.5) lo ignoran.
    reason: AiUnavailableReason | None = None
