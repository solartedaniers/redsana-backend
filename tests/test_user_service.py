"""Chequeo minimo sin DB/red: valida el auto-provisioning contra un repositorio en memoria."""
import uuid

from app.models.role import Role
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.user_service import UserService


class FakeUserRepository(UserRepository):
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)

    def create(self, user_id: uuid.UUID, email: str, full_name: str | None, role_name: str) -> User:
        user = User(id=user_id, email=email, full_name=full_name, role=Role(id=1, name=role_name))
        self.users[user_id] = user
        return user


def test_first_login_auto_provisions_user_with_default_role() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    sub = str(uuid.uuid4())
    claims = {"sub": sub, "email": "new@redsana.dev", "user_metadata": {"full_name": "Nueva Persona"}}

    user = service.get_or_create_current_user(claims)

    assert user.id == uuid.UUID(sub)
    assert user.email == "new@redsana.dev"
    assert user.role.name == "standard"
    assert repository.get_by_id(user.id) is user


def test_existing_user_is_returned_without_creating_again() -> None:
    repository = FakeUserRepository()
    service = UserService(repository)
    sub = str(uuid.uuid4())
    claims = {"sub": sub, "email": "existing@redsana.dev"}

    first_call = service.get_or_create_current_user(claims)
    second_call = service.get_or_create_current_user(claims)

    assert first_call is second_call
    assert len(repository.users) == 1


if __name__ == "__main__":
    test_first_login_auto_provisions_user_with_default_role()
    test_existing_user_is_returned_without_creating_again()
    print("OK")
