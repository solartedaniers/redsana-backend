import uuid

from pydantic import BaseModel


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    avatar_url: str | None
    role: str
    is_active: bool


class UserUpdate(BaseModel):
    # exclude_unset en el service distingue "no enviado" de "enviado como null"
    full_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
