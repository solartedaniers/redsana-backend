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
    # exclude_unset en el service distingue "no enviado" de "enviado como null".
    # Sin email a proposito: el correo es la identidad de Supabase Auth y no se
    # edita desde el perfil (pydantic ignora el campo si un cliente lo envia).
    full_name: str | None = None
    avatar_url: str | None = None
