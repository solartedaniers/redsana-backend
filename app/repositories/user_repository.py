import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.models.user import User


class UserRepository(ABC):
    """Contrato de acceso a datos para usuarios, independiente de la implementacion concreta."""

    @abstractmethod
    def get_by_id(self, user_id: uuid.UUID) -> User | None: ...

    @abstractmethod
    def create(self, user_id: uuid.UUID, email: str, full_name: str | None, role_name: str) -> User: ...

    @abstractmethod
    def update(self, user_id: uuid.UUID, updates: dict[str, Any]) -> User: ...

    @abstractmethod
    def list_all(self) -> list[User]: ...

    @abstractmethod
    def delete(self, user_id: uuid.UUID) -> None: ...
