from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_claims
from app.models.user import User
from app.repositories.user_sqlalchemy_repository import SqlAlchemyUserRepository
from app.schemas.user import UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/api", tags=["me"])


def _to_user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.name,
        is_active=user.is_active,
    )


@router.get("/me", response_model=UserRead)
def read_current_user(
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> UserRead:
    service = UserService(SqlAlchemyUserRepository(db))
    user = service.get_or_create_current_user(claims)
    return _to_user_read(user)


@router.patch("/me", response_model=UserRead)
def update_current_user(
    payload: UserUpdate,
    claims: dict[str, Any] = Depends(get_current_claims),
    db: Session = Depends(get_db),
) -> UserRead:
    service = UserService(SqlAlchemyUserRepository(db))
    user = service.update_current_user(claims, payload)
    return _to_user_read(user)
