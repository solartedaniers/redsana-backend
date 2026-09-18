import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.user import User
from app.repositories.user_repository import UserRepository


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._db.get(User, user_id)

    def list_all(self) -> list[User]:
        return list(self._db.scalars(select(User).order_by(User.created_at)).all())

    def create(self, user_id: uuid.UUID, email: str, full_name: str | None, role_name: str) -> User:
        role = self._get_role_by_name(role_name)
        user = User(id=user_id, email=email, full_name=full_name, role_id=role.id)
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        return user

    def update(self, user_id: uuid.UUID, updates: dict[str, Any]) -> User:
        user = self._db.get(User, user_id)
        if user is None:
            raise ValueError(f"User '{user_id}' does not exist")

        for field, value in updates.items():
            if field == "role_name":
                user.role_id = self._get_role_by_name(value).id
            else:
                setattr(user, field, value)

        self._db.commit()
        self._db.refresh(user)
        return user

    def delete(self, user_id: uuid.UUID) -> None:
        user = self._db.get(User, user_id)
        if user is None:
            raise ValueError(f"User '{user_id}' does not exist")

        self._db.delete(user)
        self._db.commit()

    def _get_role_by_name(self, role_name: str) -> Role:
        role = self._db.query(Role).filter(Role.name == role_name).first()
        if role is None:
            raise ValueError(f"Role '{role_name}' does not exist")
        return role
