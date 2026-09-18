import uuid

from app.core.supabase_admin_client import SupabaseAdminClient
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.admin import AdminUserCreate, AdminUserUpdate


class UserNotFoundError(Exception):
    pass


class AdminUserService:
    def __init__(self, user_repository: UserRepository, supabase_admin_client: SupabaseAdminClient) -> None:
        self._user_repository = user_repository
        self._supabase_admin_client = supabase_admin_client

    def list_users(self) -> list[User]:
        return self._user_repository.list_all()

    def create_user(self, payload: AdminUserCreate) -> User:
        # El id real lo asigna Supabase Auth al crear la identidad; recien
        # despues se puede espejar la fila local con ese mismo id.
        user_id = self._supabase_admin_client.invite_user(payload.email, payload.full_name)
        return self._user_repository.create(
            user_id=user_id,
            email=payload.email,
            full_name=payload.full_name,
            role_name=payload.role,
        )

    def update_user(self, user_id: uuid.UUID, payload: AdminUserUpdate) -> User:
        updates: dict[str, object] = {}
        if payload.full_name is not None:
            updates["full_name"] = payload.full_name
        if payload.email is not None:
            updates["email"] = payload.email
        if payload.role is not None:
            updates["role_name"] = payload.role
        if payload.status is not None:
            updates["is_active"] = payload.status == "active"

        if not updates:
            user = self._user_repository.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError(f"User '{user_id}' does not exist")
            return user

        try:
            return self._user_repository.update(user_id, updates)
        except ValueError as error:
            raise UserNotFoundError(str(error)) from error

    def delete_user(self, user_id: uuid.UUID) -> None:
        # Se borra primero en Supabase: si eso falla, la fila local sigue
        # intacta. Si se borrara primero la fila local y Supabase fallara,
        # el usuario podria loguearse de nuevo y auto-provisionarse otra vez.
        self._supabase_admin_client.delete_user(user_id)
        try:
            self._user_repository.delete(user_id)
        except ValueError as error:
            raise UserNotFoundError(str(error)) from error
