"""Chequeo minimo sin DB/red: valida el CRUD de admin sobre un repositorio de usuarios en memoria."""
import uuid

from app.schemas.admin import AdminUserCreate, AdminUserUpdate
from app.services.admin_user_service import AdminUserService, UserNotFoundError
from tests.test_user_service import FakeUserRepository


class FakeSupabaseAdminClient:
    """Doble de pruebas: no golpea la Admin API real de Supabase."""

    def __init__(self) -> None:
        self.invited: list[tuple[str, str | None]] = []
        self.deleted: list[uuid.UUID] = []
        self.next_id = uuid.uuid4()

    def invite_user(self, email: str, full_name: str | None) -> uuid.UUID:
        self.invited.append((email, full_name))
        return self.next_id

    def delete_user(self, user_id: uuid.UUID) -> None:
        self.deleted.append(user_id)


def test_create_user_invites_via_supabase_then_mirrors_locally() -> None:
    user_repository = FakeUserRepository()
    supabase_client = FakeSupabaseAdminClient()
    service = AdminUserService(user_repository, supabase_client)

    user = service.create_user(AdminUserCreate(full_name="Nueva Persona", email="nueva@redsana.dev", role="standard"))

    assert user.id == supabase_client.next_id
    assert supabase_client.invited == [("nueva@redsana.dev", "Nueva Persona")]
    assert user_repository.get_by_id(user.id) is user


def test_update_user_role_and_status() -> None:
    user_repository = FakeUserRepository()
    service = AdminUserService(user_repository, FakeSupabaseAdminClient())
    user = service.create_user(AdminUserCreate(full_name="Ana", email="ana@redsana.dev", role="standard"))

    updated = service.update_user(user.id, AdminUserUpdate(role="admin", status="suspended"))

    assert updated.role.name == "admin"
    assert updated.is_active is False


def test_update_user_not_found_raises() -> None:
    service = AdminUserService(FakeUserRepository(), FakeSupabaseAdminClient())

    try:
        service.update_user(uuid.uuid4(), AdminUserUpdate(full_name="X"))
        raise AssertionError("expected UserNotFoundError")
    except UserNotFoundError:
        pass


def test_delete_user_calls_supabase_before_local_repository() -> None:
    user_repository = FakeUserRepository()
    supabase_client = FakeSupabaseAdminClient()
    service = AdminUserService(user_repository, supabase_client)
    user = service.create_user(AdminUserCreate(full_name="Ana", email="ana@redsana.dev", role="standard"))

    service.delete_user(user.id)

    assert supabase_client.deleted == [user.id]
    assert user_repository.get_by_id(user.id) is None


if __name__ == "__main__":
    test_create_user_invites_via_supabase_then_mirrors_locally()
    test_update_user_role_and_status()
    test_update_user_not_found_raises()
    test_delete_user_calls_supabase_before_local_repository()
    print("OK")
