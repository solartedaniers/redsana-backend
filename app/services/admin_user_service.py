import uuid

from app.core.authorization import ADMIN_ROLE_NAME
from app.core.supabase_admin_client import SupabaseAdminClient
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.admin import AdminUserCreate, AdminUserUpdate


class UserNotFoundError(Exception):
    pass


class AdminLockoutError(Exception):
    """La operación dejaría al admin actual sin acceso o a la plataforma sin ningún admin activo."""


class AdminUserService:
    def __init__(self, user_repository: UserRepository, supabase_admin_client: SupabaseAdminClient) -> None:
        self._user_repository = user_repository
        self._supabase_admin_client = supabase_admin_client

    def list_users(self) -> list[User]:
        return self._user_repository.list_all()

    def create_user(self, payload: AdminUserCreate) -> User:
        # El id lo asigna Supabase al crear la identidad; recién entonces puedo crear la fila local con ese id.
        user_id = self._supabase_admin_client.invite_user(payload.email, payload.full_name)
        return self._user_repository.create(
            user_id=user_id,
            email=payload.email,
            full_name=payload.full_name,
            role_name=payload.role,
        )

    def update_user(self, user_id: uuid.UUID, payload: AdminUserUpdate, acting_admin_id: uuid.UUID) -> User:
        updates: dict[str, object] = {}
        if payload.full_name is not None:
            updates["full_name"] = payload.full_name
        if payload.email is not None:
            updates["email"] = payload.email
        if payload.role is not None:
            updates["role_name"] = payload.role
        if payload.status is not None:
            updates["is_active"] = payload.status == "active"
        if updates.get("is_active") is False or updates.get("role_name", ADMIN_ROLE_NAME) != ADMIN_ROLE_NAME:
            self._ensure_admin_access_can_be_removed(user_id, acting_admin_id)

        if not updates:
            user = self._user_repository.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError(f"User '{user_id}' does not exist")
            return user

        try:
            return self._user_repository.update(user_id, updates)
        except ValueError as error:
            raise UserNotFoundError(str(error)) from error

    def delete_user(self, user_id: uuid.UUID, acting_admin_id: uuid.UUID) -> None:
        self._ensure_admin_access_can_be_removed(user_id, acting_admin_id)
        # Borro primero en Supabase: si fallara después de borrar la fila local, el usuario podría volver a entrar y recrearse.
        self._supabase_admin_client.delete_user(user_id)
        try:
            self._user_repository.delete(user_id)
        except ValueError as error:
            raise UserNotFoundError(str(error)) from error

    def _ensure_admin_access_can_be_removed(self, user_id: uuid.UUID, acting_admin_id: uuid.UUID) -> None:
        if user_id == acting_admin_id:
            raise AdminLockoutError("Admins cannot remove their own admin access")
        target = self._user_repository.get_by_id(user_id)
        if target is None or not _is_active_admin(target):
            return
        # Recorre todos los usuarios (decenas hoy); con miles conviene una consulta de conteo en el repositorio.
        if not any(_is_active_admin(user) for user in self._user_repository.list_all() if user.id != user_id):
            raise AdminLockoutError("At least one active admin is required")


def _is_active_admin(user: User) -> bool:
    # Igual que reject_suspended: solo un False explícito cuenta como suspendido.
    return user.role.name == ADMIN_ROLE_NAME and user.is_active is not False
