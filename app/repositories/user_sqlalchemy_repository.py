import uuid

from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.user import User
from app.repositories.user_repository import UserRepository


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self._db.get(User, user_id)

    def create(self, user_id: uuid.UUID, email: str, full_name: str | None, role_name: str) -> User:
        role = self._db.query(Role).filter(Role.name == role_name).first()
        if role is None:
            raise ValueError(f"Role '{role_name}' does not exist")

        user = User(id=user_id, email=email, full_name=full_name, role_id=role.id)
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        return user
