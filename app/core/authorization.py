from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_claims
from app.models.user import User
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.services.user_service import UserService

ADMIN_ROLE_NAME = "admin"


def get_current_user(
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> User:
    """Resuelve el usuario propio completo, con su rol; va aparte porque necesita la base de datos."""
    service = UserService(SqlAlchemyUserRepository(db))
    return service.get_or_create_current_user(claims)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role.name != ADMIN_ROLE_NAME:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
