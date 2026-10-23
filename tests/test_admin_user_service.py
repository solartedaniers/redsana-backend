"""Sin base ni red: CRUD de admin sobre un repositorio de usuarios en memoria."""
import uuid

import pytest

from app.schemas.admin import AdminUserCreate, AdminUserUpdate
from app.services.admin_user_service import AdminLockoutError, AdminUserService, UserNotFoundError
from tests.test_user_service import FakeUserRepository

# Quien hace la operación en las pruebas que no tratan sobre la guarda del admin sobre sí mismo.
OTHER_ADMIN_ID = uuid.uuid4()


class FakeSupabaseAdminClient:
    """Doble de pruebas: no llama a la Admin API real de Supabase."""

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

    updated = service.update_user(user.id, AdminUserUpdate(role="admin", status="suspended"), OTHER_ADMIN_ID)

    assert updated.role.name == "admin"
    assert updated.is_active is False


def test_update_user_not_found_raises() -> None:
    service = AdminUserService(FakeUserRepository(), FakeSupabaseAdminClient())

    try:
        service.update_user(uuid.uuid4(), AdminUserUpdate(full_name="X"), OTHER_ADMIN_ID)
        raise AssertionError("expected UserNotFoundError")
    except UserNotFoundError:
        pass


def test_delete_user_calls_supabase_before_local_repository() -> None:
    user_repository = FakeUserRepository()
    supabase_client = FakeSupabaseAdminClient()
    service = AdminUserService(user_repository, supabase_client)
    user = service.create_user(AdminUserCreate(full_name="Ana", email="ana@redsana.dev", role="standard"))

    service.delete_user(user.id, OTHER_ADMIN_ID)

    assert supabase_client.deleted == [user.id]
    assert user_repository.get_by_id(user.id) is None


def _with_admins(count: int) -> tuple[AdminUserService, FakeUserRepository, FakeSupabaseAdminClient, list[uuid.UUID]]:
    user_repository = FakeUserRepository()
    supabase_client = FakeSupabaseAdminClient()
    ids = [uuid.uuid4() for _ in range(count)]
    for index, admin_id in enumerate(ids):
        user_repository.create(admin_id, f"admin{index}@redsana.dev", f"Admin {index}", "admin")
    return AdminUserService(user_repository, supabase_client), user_repository, supabase_client, ids


@pytest.mark.parametrize("payload", [AdminUserUpdate(status="suspended"), AdminUserUpdate(role="standard")])
def test_an_admin_cannot_suspend_or_demote_themself(payload: AdminUserUpdate) -> None:
    service, user_repository, _, (me, _other) = _with_admins(2)

    with pytest.raises(AdminLockoutError):
        service.update_user(me, payload, acting_admin_id=me)

    me_after = user_repository.get_by_id(me)
    assert (me_after.role.name, me_after.is_active) == ("admin", True)


def test_an_admin_cannot_delete_themself_and_supabase_is_not_called() -> None:
    service, user_repository, supabase_client, (me, _other) = _with_admins(2)

    with pytest.raises(AdminLockoutError):
        service.delete_user(me, acting_admin_id=me)

    assert supabase_client.deleted == []
    assert user_repository.get_by_id(me) is not None


def test_an_admin_can_still_edit_their_own_name_and_keep_the_admin_role() -> None:
    service, _, _, (me,) = _with_admins(1)

    updated = service.update_user(me, AdminUserUpdate(full_name="Nuevo", role="admin", status="active"), me)

    assert updated.full_name == "Nuevo"


def test_an_admin_can_suspend_demote_and_delete_another_admin_while_one_stays_active() -> None:
    service, user_repository, _, (me, other, third) = _with_admins(3)

    service.update_user(other, AdminUserUpdate(status="suspended"), acting_admin_id=me)
    service.update_user(third, AdminUserUpdate(role="standard"), acting_admin_id=me)
    service.delete_user(third, acting_admin_id=me)

    assert user_repository.get_by_id(other).is_active is False
    assert user_repository.get_by_id(third) is None


@pytest.mark.parametrize("operation", ["suspend", "demote", "delete"])
def test_removing_the_last_active_admin_is_refused(operation: str) -> None:
    """Defensa aparte de la anterior: p. ej. dos admins que se quitan el rol uno al otro al mismo tiempo."""
    service, user_repository, supabase_client, (last, suspended) = _with_admins(2)
    user_repository.update(suspended, {"is_active": False})
    acting = uuid.uuid4()  # el que actúa ya no figura como admin activo

    with pytest.raises(AdminLockoutError):
        if operation == "delete":
            service.delete_user(last, acting_admin_id=acting)
        else:
            payload = AdminUserUpdate(status="suspended") if operation == "suspend" else AdminUserUpdate(role="standard")
            service.update_user(last, payload, acting_admin_id=acting)

    assert (user_repository.get_by_id(last).role.name, user_repository.get_by_id(last).is_active) == ("admin", True)
    assert supabase_client.deleted == []


def test_standard_users_are_not_affected_by_the_admin_guard() -> None:
    service, user_repository, _, (me,) = _with_admins(1)
    standard = service.create_user(AdminUserCreate(full_name="Ana", email="ana@redsana.dev", role="standard"))

    service.update_user(standard.id, AdminUserUpdate(status="suspended"), acting_admin_id=me)

    assert user_repository.get_by_id(standard.id).is_active is False


if __name__ == "__main__":
    test_create_user_invites_via_supabase_then_mirrors_locally()
    test_update_user_role_and_status()
    test_update_user_not_found_raises()
    test_delete_user_calls_supabase_before_local_repository()
    print("OK")
