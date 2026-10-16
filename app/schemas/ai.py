from pydantic import BaseModel

from app.ai_gateway.ai_gateway import AiAvailability


class AiStatusRead(BaseModel):
    status: AiAvailability
