import uuid

from pydantic import BaseModel


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
