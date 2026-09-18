import uuid
from typing import Any

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserUpdate

DEFAULT_ROLE_NAME = "standard"


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def get_or_create_current_user(self, claims: dict[str, Any]) -> User:
        """Resuelve el usuario propio a partir de los claims del JWT de Supabase.

        Auto-provisioning: si es el primer login, crea el registro propio
        con rol por defecto; Supabase ya garantizo que la identidad es valida.
        """
        user_id = uuid.UUID(claims["sub"])
        user = self._repository.get_by_id(user_id)
        if user is not None:
            return user

        return self._repository.create(
            user_id=user_id,
            email=claims["email"],
            full_name=claims.get("user_metadata", {}).get("full_name"),
            role_name=DEFAULT_ROLE_NAME,
        )

    def update_current_user(self, claims: dict[str, Any], payload: UserUpdate) -> User:
        user_id = uuid.UUID(claims["sub"])
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return self.get_or_create_current_user(claims)
        return self._repository.update(user_id, updates)
