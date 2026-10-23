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
    return reject_suspended(service.get_or_create_current_user(claims))


def reject_suspended(user: User) -> User:
    """Un admin suspendió la cuenta: 403. Solo un False explícito suspende; un valor ausente nunca deja fuera a nadie."""
    if user.is_active is False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role.name != ADMIN_ROLE_NAME:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
